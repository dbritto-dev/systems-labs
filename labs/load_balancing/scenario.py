"""Lab load_balancing: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (Poisson, drifting slowly like real traffic). Each request
reaches one of 4 load balancers (round robin DNS), and that balancer's `Balancer.pick()`
chooses one of 8 servers. A server works on 4 requests at once (~20 ms each) and queues
the rest. The balancers learn how busy the servers are from a load report: every 0.5 s
each one reads how many requests each server had in flight on average over the last
0.5 s, so its view is stale. A request that has not been answered after 1 s times out (a
504); the server does not know and still works on it.

Incidents come at random, like in production: one server turns slow (a noisy neighbour, a
GC storm, a failing disk, a degraded availability zone) or is replaced by a cold one (the
autoscaler, a reclaimed spot instance, a deploy: empty caches, a cold JIT) that is slow
until it warms up. The first incident is always a slow server at 0:20-0:32. The run never
restarts: queues, load reports and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now

LAB = "load_balancing"
NAMES = ("Balancer", "least_outstanding", "two_choices")
PIECE = 60.0
DRAIN = 5.0  # simulate this far past a minute before handing it out (every request ends by then)
SAMPLE = 0.1  # how often the servers' loads are recorded

SERVERS = 8
BALANCERS = 4
WORKERS = 4  # requests a server works on at once; the rest wait in its queue
SERVICE = 0.040  # seconds per request on a healthy server (±50%): 100 requests/s per server
TIMEOUT = 1.0  # the balancer gives up on a request after this long (504)
METER = 0.025  # how often a server counts its requests in flight, for the load report
REPORT = 0.5  # seconds between load reports; each balancer reads its own at its own moment

# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 32.0, "slow", 5.0, "noisy_neighbour")
FIRST_SERVER = 2
KINDS = [
    Kind("slow", 0.6, median=11.0, shortest=8.0, longest=16.0, severity=(3.5, 5.0), causes=(
        "noisy_neighbour", "gc_storm", "bad_disk", "degraded_az")),
    Kind("cold", 0.4, median=11.0, shortest=8.0, longest=15.0, severity=(5.0, 9.0), causes=(
        "autoscaler", "spot_reclaimed", "deploy_restart")),
]
MEAN_GAP = 30.0
QUIET = 22.0  # at least this calm after an incident: a 15 s baseline + time to judge it


def _s(key: str, **values) -> str:
    """One of the lab's STRINGS in the language in use (errors your code may see)."""
    return lab_text(LAB).STRINGS[key].format(**values)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def sick_servers(seed: int) -> Iterator[int]:
    """Which server each incident hits, in order (the first one always hits server 2)."""
    rng = random.Random(seed * 7 + 3)
    yield FIRST_SERVER
    while True:
        yield rng.randrange(SERVERS)


class Server:
    """One server: WORKERS requests at a time, first come first served, the rest wait in a queue.

    Requests are worked out as they arrive (a FIFO queue lets you): when a worker frees up, how
    long the request takes at the server's speed then, and whether the balancer gives up first.
    The server cannot tell that the balancer gave up (a 504 to the user): it still works on the
    request, and counts it as outstanding, until it is done.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.free = [0.0] * WORKERS  # when each worker is next free (a heap)
        self.ends: list[float] = []  # when each request sent to it is done (a heap)
        self.incident: Planned | None = None  # what makes it slow, if anything

    def slow(self, t: float) -> float:
        """How many times slower than healthy it is at time t."""
        inc = self.incident
        if inc is None or not inc.t0 <= t < inc.t1:
            return 1.0
        if inc.kind == "slow":
            return inc.severity
        warm = (t - inc.t0) / (inc.t1 - inc.t0)  # a cold server warms up until the incident ends
        return 1.0 + (inc.severity - 1.0) * (1.0 - warm)

    def handle(self, t: float) -> tuple[float, bool]:
        """A request arrives at t: (when it ends, whether it was answered before the timeout)."""
        start = max(t, heapq.heappop(self.free))
        done = start + SERVICE * self.slow(start) * self.rng.uniform(0.5, 1.5)
        heapq.heappush(self.free, done)
        heapq.heappush(self.ends, done)
        return min(done, t + TIMEOUT), done <= t + TIMEOUT

    def outstanding(self, t: float) -> int:
        """Requests sent to it and not done by time t: queued or running."""
        ends = self.ends
        while ends and ends[0] <= t:
            heapq.heappop(ends)
        return len(ends)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        rng = random.Random(seed * 7 + 1)
        self.servers = [Server(rng) for _ in range(SERVERS)]
        self.balancers = [code.Balancer(SERVERS, random.Random(seed * 101 + b)) for b in range(BALANCERS)]
        self.views = [[0.0] * SERVERS for _ in range(BALANCERS)]  # each balancer's last load report
        self.metered: deque[tuple[int, ...]] = deque(maxlen=round(REPORT / METER))  # in flight, last REPORT s
        self.ids = itertools.count()
        self.requests: list[tuple] = []  # (id, start, end, ok, balancer, server, to the sick server)
        self.samples: list[tuple] = []  # (t, sick server or -1, its slowness, outstanding per server)
        self.planned: list[Planned] = []
        self.sick_rows: list[tuple] = []  # (t0, t1, server): which server each incident hits
        self.sick = -1
        self.bugs: list[BaseException] = []

    def request(self, rid: int, t: float) -> None:
        b = rid % BALANCERS  # DNS spreads users over the balancers
        i = self.balancers[b].pick(list(self.views[b]))
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < SERVERS:
            raise ValueError(_s("bad_pick", value=repr(i), last=SERVERS - 1))
        end, ok = self.servers[i].handle(t)
        self.requests.append((rid, t, end, ok, b, i, i == self.sick))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            try:
                self.request(next(self.ids), now())
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return

    async def meter(self) -> None:
        """Each server counts its requests in flight every METER seconds, for its load report."""
        while True:
            t = now()
            self.metered.append(tuple(s.outstanding(t) for s in self.servers))
            await asyncio.sleep(METER)

    async def reports(self, b: int) -> None:
        """Balancer b reads a fresh load report every REPORT seconds, each at its own moment: each
        server's average number of requests in flight over the REPORT seconds before."""
        await asyncio.sleep(REPORT * b / BALANCERS + METER / 2)
        while True:
            n = max(1, len(self.metered))
            self.views[b] = [round(sum(m[i] for m in self.metered) / n, 2) for i in range(SERVERS)]
            await asyncio.sleep(REPORT)

    async def chaos(self) -> None:
        which = sick_servers(self.seed)
        for inc in incidents(self.seed):
            self.planned.append(inc)
            i = next(which)
            self.sick_rows.append((inc.t0, inc.t1, i))
            await asyncio.sleep(inc.t0 - now())
            self.sick = i
            self.servers[i].incident = inc
            await asyncio.sleep(inc.t1 - now())
            self.sick = -1

    async def sampler(self) -> None:
        while True:
            t = now()
            slow = self.servers[self.sick].slow(t) if self.sick >= 0 else 1.0
            self.samples.append((round(t, 3), self.sick, round(slow, 2),
                                 tuple(s.outstanding(t) for s in self.servers)))
            await asyncio.sleep(SAMPLE)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 250.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for task in (s.traffic(), s.chaos(), s.sampler(), s.meter(), *(s.reports(b) for b in range(BALANCERS))):
        sim.spawn(task)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "samples": s.take(s.samples, 0, a, b),
                    "sick": s.take(s.sick_rows, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 250.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
