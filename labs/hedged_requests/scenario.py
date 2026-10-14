"""Lab hedged_requests: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` reads/s (Poisson, drifting slowly like real traffic) through
your `Client`, which asks one or more of 3 replicas. A reply takes ~10 ms, but
1 in 50 takes 100-400 ms (a GC pause, a cache miss, a slow disk). A user gives up
after DEADLINE seconds.

Incidents come at random, like in production: one replica gets much slower for a
while (a compaction, a noisy neighbour, a degraded volume: 0.2-0.8 s a reply), or
every replica gets a few times slower (a hot key, cold caches after a deploy). The
first incident is always replica 2 at 0:20-0:30, 0.5 s a reply (a compaction).

The run never restarts: your hedge budget, the replicas and the clock carry on
from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import current_request
from core.vtime import VirtualRun, now

LAB = "hedged_requests"
NAMES = ("Client", "HedgeBudget")
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a read still running after this long is a bug
DEADLINE = 1.0  # a user gives up after this long
REPLICAS = 3
# A normal reply: 8 ms plus an exponential tail (mean 2 ms): p50 ~9 ms, p95 ~14 ms.
FLOOR, SPREAD = 0.008, 0.002
HICCUP = 0.02  # the share of replies that are slow anyway (GC pause, cache miss, slow disk)
HICCUP_TIME = (0.1, 0.4)  # seconds such a reply takes
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
# A kind "r0".."r2" slows one replica down (severity: seconds a reply); "all" slows every replica
# (severity: seconds a normal reply takes).
FIRST = Planned(20.0, 30.0, "r1", 0.5, "compaction")
_ONE = ("compaction", "noisy_neighbour", "degraded_volume", "backup_snapshot", "index_rebuild")
KINDS = [
    *(Kind(f"r{i}", 0.2, median=10.0, shortest=6.0, longest=25.0, severity=(0.2, 0.8), causes=_ONE)
      for i in range(REPLICAS)),
    Kind("all", 0.4, median=10.0, shortest=6.0, longest=25.0, severity=(0.03, 0.06), causes=(
        "hot_key", "cold_caches", "slow_storage", "zone_congestion")),
]
MEAN_GAP = 30.0
QUIET = 28.0  # at least this calm after an incident: 13 s to judge it + a 15 s baseline

# Read outcomes.
OK, WRONG, GAVE_UP = range(3)  # answered; answered with something a replica never said; the user left
# Call outcomes.
CALL_OK, CALL_CUT = range(2)  # answered; cancelled before it answered


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def value_of(key) -> str:
    return f"value-{key}"


class Replica:
    """What your Client calls: one copy of the data, recording every call it gets."""

    def __init__(self, index: int, sim: "_Sim") -> None:
        self.index, self.sim = index, sim
        self.name = f"replica {index + 1}"

    def __repr__(self) -> str:
        return f"<Replica {self.index + 1}>"

    async def get(self, key):
        """The value of `key`, after however long this replica takes."""
        sim = self.sim
        rid = current_request.get()
        start, outcome = now(), CALL_CUT
        copy = sim.copies.get(rid, 0)
        sim.copies[rid] = copy + 1
        if copy == 1:
            sim.hedged[rid] = start
        sim.running[rid] = sim.running.get(rid, 0) + 1
        try:
            await asyncio.sleep(sim.latency(self.index))
            outcome = CALL_OK
            return value_of(key)
        finally:
            end = now()
            done = sim.done.get(rid)  # the read was already answered: this call is wasted work
            sim.calls.append((start, rid, self.index, end, outcome, copy,
                              0.0 if done is None else max(0.0, end - max(done, start))))
            sim.running[rid] -= 1
            if not sim.running[rid]:
                del sim.running[rid]
                sim.done.pop(rid, None)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.rng = random.Random(seed * 11 + 3)
        self.replicas = [Replica(i, self) for i in range(REPLICAS)]
        self.client = code.Client(list(self.replicas), rng=random.Random(seed * 11 + 5))
        self.slow: dict[int, float] = {}  # replica -> seconds a reply takes, while it is slow
        self.all_slow = 0.0  # seconds a normal reply takes while every replica is slow (0 = normal)
        # (id, start, end, outcome, copies sent, when the second copy was sent or None)
        self.requests: list[tuple] = []
        # (start, request id, replica, end, outcome, copy number, seconds run after the read was answered)
        self.calls: list[tuple] = []
        self.copies: dict[int, int] = {}  # request id -> calls made so far
        self.hedged: dict[int, float] = {}  # request id -> when its second call started
        self.running: dict[int, int] = {}  # request id -> calls still running
        self.done: dict[int, float] = {}  # request id -> answered at (while some call still runs)
        self.open: dict[int, float] = {}
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    def latency(self, replica: int) -> float:
        rng = self.rng
        if replica in self.slow:
            return self.slow[replica] * rng.uniform(0.8, 1.2)
        if rng.random() < HICCUP:
            return rng.uniform(*HICCUP_TIME)
        if self.all_slow:
            return self.all_slow * rng.uniform(0.7, 1.3)
        return FLOOR + rng.expovariate(1.0 / SPREAD)

    async def user(self, rid: int) -> None:
        current_request.set(rid)
        start = now()
        self.open[rid] = start
        try:
            async with asyncio.timeout(DEADLINE):
                value = await self.client.read(rid)
            outcome = OK if value == value_of(rid) else WRONG
        except TimeoutError:
            outcome = GAVE_UP
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        end = now()
        copies = self.copies.pop(rid, 0)
        hedged = self.hedged.pop(rid, None)
        if rid in self.running:
            self.done[rid] = end
        self.requests.append((rid, start, end, outcome, copies, hedged))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11)
        for rid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.user(rid))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "all":
                self.all_slow = inc.severity
            else:
                self.slow[int(inc.kind[1:])] = inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.slow.clear()
            self.all_slow = 0.0

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 100.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.open.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "calls": s.take(s.calls, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
