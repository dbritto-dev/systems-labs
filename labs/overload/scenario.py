"""Lab overload: one endless run on virtual time, handed out a minute at a time.

A server works through a queue, one request at a time: 10 ms each, so it does
100 requests/s. Users send ~75 requests/s (Poisson, drifting slowly). A user
waits 1 s for a reply, then gives up on that try and sends it again (at most 2
retries). The try they gave up on stays in the queue: whether the server still
works on it is up to your `Policy`. A rejection is an answer: no retry.

Incidents come at random, like in production: traffic spikes (2-3x) and
capacity drops (the server runs at 30-50% speed). The first one is always a
2.5x spike at 0:20-0:30. The run never restarts: a queue full of requests for
users who already left carries on into the next minute.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, rate_at, schedule
from core.vtime import VirtualRun, now

LAB = "overload"
NAMES = ("Policy", "Request")
PIECE = 60.0
DRAIN = 5.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a user still waiting after this long is a bug
SERVICE_TIME = 0.010  # seconds per request: 100 requests/s
USER_TIMEOUT = 1.0
MAX_RETRIES = 2
SAMPLE = 0.1  # seconds between samples of the queue
FIRST = Planned(20.0, 30.0, "spike", 2.5, "a post went viral")
KINDS = [
    Kind("spike", 0.6, median=9.0, shortest=5.0, longest=15.0, severity=(2.0, 3.0), causes=(
        "a post went viral",
        "a thundering herd after a deploy",
        "a partner's batch job started early",
        "a retry storm from a mobile app release",
        "a cache in front of it was flushed",
    )),
    Kind("capacity", 0.4, median=10.0, shortest=6.0, longest=20.0, severity=(0.3, 0.5), causes=(
        "one of its nodes was lost",
        "a noisy neighbour is starving the CPU",
        "a bad config halved the workers",
        "garbage collection pauses",
    )),
]
MEAN_GAP = 30.0
QUIET = 32.0  # calm after an incident: 15 s to judge recovery + a 15 s baseline

# What happened to a try (as seen by its user), and to a piece of server work.
OK, GAVE_UP, REJECTED = range(3)
IN_TIME, LATE, SKIPPED = range(3)
# What happened to a user's request in the end.
SERVED, FAILED, REFUSED = range(3)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code = code
        self.policy = code.Policy()
        self.seed, self.rate = seed, rate
        self.service_time = SERVICE_TIME
        self.extra = 0.0  # extra arrival rate during a spike
        self.queue: deque = deque()  # (request, record), oldest on the left
        self.stale = 0  # queued tries whose user already gave up
        self.wake = asyncio.Event()
        self.aids = itertools.count()
        self.clients = itertools.count()
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, list] = {}  # client -> [first sent, tries so far]
        # Finished rows waiting to be handed out.
        self.tries: list[tuple] = []  # (sent, try id, client, attempt, answered or gave up, result)
        self.work: list[tuple] = []  # (start, try id, end, kind)
        self.requests: list[tuple] = []  # (client, first sent, done, outcome, tries)
        self.samples: list[tuple] = []  # (t, queue length, stale in queue)

    # ---- users

    def _guard(self, fn, *args) -> None:
        """Run a callback; a bug in your Policy is reported, not swallowed by the loop."""
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            self.bugs.append(exc)

    def new_user(self) -> None:
        client = next(self.clients)
        self.open[client] = [now(), 0]
        self.send(client, 0)

    def send(self, client: int, attempt: int) -> None:
        t = now()
        aid = next(self.aids)
        self.open[client][1] += 1
        req = self.code.Request(aid, t, attempt)
        rec = [t, aid, client, attempt, None, None, False]  # ..., answered at, result, queued
        if not self.policy.admit(req, len(self.queue), t):
            self._answer(rec, REJECTED)
            self._done(client, REFUSED)
            return
        rec[6] = True
        self.queue.append((req, rec))
        self.wake.set()
        asyncio.get_running_loop().call_later(USER_TIMEOUT, self._guard, self._timeout, rec)

    def _timeout(self, rec: list) -> None:
        if rec[5] is not None:
            return
        self._answer(rec, GAVE_UP)
        if rec[6]:
            self.stale += 1
        client, attempt = rec[2], rec[3]
        if attempt < MAX_RETRIES:
            self.send(client, attempt + 1)
        else:
            self._done(client, FAILED)

    def _answer(self, rec: list, result: int) -> None:
        rec[4], rec[5] = now(), result
        self.tries.append((rec[0], rec[1], rec[2], rec[3], rec[4], result))

    def _done(self, client: int, outcome: int) -> None:
        first, tries = self.open.pop(client)
        self.requests.append((client, first, now(), outcome, tries))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            self.new_user()

    async def surge(self, t1: float) -> None:
        """Extra users during a spike, on top of the normal traffic."""
        rng = random.Random(self.seed * 7 + int(t1 * 10))
        while True:
            rate = self.extra * rate_at(self.rate, now(), self.seed)
            await asyncio.sleep(rng.expovariate(rate))
            if now() >= t1:
                return
            self.new_user()

    # ---- the server

    async def server(self) -> None:
        while True:
            while not self.queue:
                self.wake.clear()
                await self.wake.wait()
            newest = self.policy.newest_first(len(self.queue), now())
            req, rec = self.queue.pop() if newest else self.queue.popleft()
            rec[6] = False
            if rec[5] is not None:
                self.stale -= 1
            if self.policy.drop(req, now()):
                self.work.append((now(), rec[1], now(), SKIPPED))
                continue
            start = now()
            await asyncio.sleep(self.service_time)
            if rec[5] is None:
                self._answer(rec, OK)
                self._done(rec[2], SERVED)
                kind = IN_TIME
            else:
                kind = LATE  # the user already left: wasted work
            self.work.append((start, rec[1], now(), kind))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "spike":
                self.extra = inc.severity - 1.0
                asyncio.ensure_future(self.surge(inc.t1))
            else:
                self.service_time = SERVICE_TIME / inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.extra = 0.0
            self.service_time = SERVICE_TIME

    async def sampler(self) -> None:
        while True:
            self.samples.append((now(), len(self.queue), self.stale))
            await asyncio.sleep(SAMPLE)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 75.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for task in (s.traffic(), s.server(), s.chaos(), s.sampler()):
        sim.spawn(task)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(first < b + DRAIN - STUCK for first, _ in s.open.values()):
                raise RuntimeError(f"a user has been waiting for over {STUCK:.0f} s")
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "tries": s.take(s.tries, 0, a, b),
                    "work": s.take(s.work, 0, a, b),
                    "queue": s.take(s.samples, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 75.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
