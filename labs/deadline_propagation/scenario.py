"""Lab deadline_propagation: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (Poisson, drifting slowly like real traffic) to the
gateway, with their deadline in the headers: they give up after USER_DEADLINE
seconds. Every request goes down a chain of four services, gateway → api → orders
→ db. Each service has a pool of workers; a request waits for one, then the
service runs your `handle`: its own work (a few ms; the db's query), then a call to
the next service, holding the worker while it waits. A call is a network request:
when the caller stops waiting, the callee does not know and carries on.

Incidents come at random, like in production: the db gets slow, 120-160 ms a query
instead of 15 (a slow query plan, lock contention, a degraded replica, a GC storm, a
vacuum, a cold cache after a failover). Its few connections then do fewer queries a
second than users ask for, and a queue forms in front of it. The first incident is
always at 0:20-0:30, 150 ms a query.

The run never restarts: the queues, the workers and the clock carry on from one
minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import ServiceError
from core.vtime import VirtualRun, now

LAB = "deadline_propagation"
NAMES = ("handle", "next_deadline", "expired", "DeadlineExceeded", "HOP_TIMEOUT", "MARGIN")
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a request still holding a worker after this long is a bug
USER_DEADLINE = 2.0  # a user gives up after this long
HOPS = ("gateway", "api", "orders", "db")
WORKERS = (200, 75, 75)  # workers at the gateway, api and orders; the db has `connections`
WORK = (0.002, 0.010, 0.010, 0.015)  # seconds of each service's own work, normally
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "db", 0.15, "slow_query")
KINDS = [
    Kind("db", 1.0, median=10.0, shortest=6.0, longest=22.0, severity=(0.12, 0.16), causes=(
        "slow_query", "lock_contention", "degraded_replica", "gc_storm", "vacuum", "cold_cache")),
]
MEAN_GAP = 30.0
QUIET = 26.0  # at least this calm after an incident: ~10 s to judge it + a 15 s baseline

# Request outcomes (the user's side).
OK, FAILED, GAVE_UP = range(3)  # served in time; an error before the deadline; the user left
# Call outcomes (one service calling the next).
CALL_OK, CALL_ERROR, CALL_CUT = range(3)  # answered; failed; the caller stopped waiting


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class Hop:
    """What your `handle` gets: one service, serving one request."""

    __slots__ = ("sim", "index", "rid", "name", "last", "began", "done")

    def __init__(self, sim: "_Sim", index: int, rid: int) -> None:
        self.sim, self.index, self.rid = sim, index, rid
        self.name = HOPS[index]
        self.last = index == len(HOPS) - 1
        self.began = self.done = None  # when its own work ran

    async def work(self) -> None:
        """This service's own work (the db's query): it holds the worker and cannot be stopped."""
        s = self.sim
        self.began = now()
        await asyncio.sleep(s.cost[self.index] * (0.8 + 0.4 * s.rng.random()))
        self.done = now()

    async def call_next(self, deadline: float | None, timeout: float | None) -> str:
        """Send the request to the next service and wait up to `timeout` s for its answer."""
        if self.last:
            raise ServiceError("the db has no next service")
        s = self.sim
        task = s.send(self.index + 1, self.rid, deadline)
        start, outcome = now(), CALL_CUT
        try:
            async with asyncio.timeout(timeout):
                ok = await asyncio.shield(task)
            outcome = CALL_OK if ok else CALL_ERROR
        except TimeoutError:
            raise ServiceError(f"{HOPS[self.index + 1]} timed out") from None
        finally:
            s.calls.append((start, self.rid, self.index, now(), outcome, s.ended.get(self.rid)))
        if not ok:
            raise ServiceError(f"{HOPS[self.index + 1]} failed")
        return "ok"


class _Sim:
    def __init__(self, code, seed: int, rate: float, connections: int) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.rng = random.Random(seed * 7 + 3)
        self.workers = [asyncio.Semaphore(n) for n in (*WORKERS, connections)]
        self.cost = list(WORK)
        self.requests: list[tuple] = []  # (id, start, end, outcome)
        # (arrived at the hop, request id, hop, got a worker, freed it, the user left at (None: still
        # waiting when it was freed), its own work began, ended (None: it skipped the work))
        self.work: list[tuple] = []
        self.calls: list[tuple] = []  # (start, request id, from hop, end, outcome, the user left at or None)
        self.ended: dict[int, float] = {}  # request id -> when its user's request ended
        self.holding: dict[tuple[int, int], float] = {}  # (request id, hop) -> arrived at
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    def send(self, hop: int, rid: int, deadline: float | None) -> asyncio.Future:
        return asyncio.ensure_future(self.serve(hop, rid, deadline))

    async def serve(self, i: int, rid: int, deadline: float | None) -> bool:
        """One service's side: wait for a worker, run `handle`, free the worker.

        It does not know whether its caller still waits: it finishes either way.
        """
        arrived = now()
        self.holding[rid, i] = arrived
        hop = Hop(self, i, rid)
        ok, got = False, arrived
        try:
            async with self.workers[i]:
                got = now()
                try:
                    await self.code.handle(hop, deadline)
                    ok = True
                except (ServiceError, TimeoutError):
                    pass
                except Exception as exc:  # a bug in the code under test: surface it
                    self.bugs.append(exc)
        finally:
            self.work.append((arrived, rid, i, got, now(), self.ended.get(rid), hop.began, hop.done))
            del self.holding[rid, i]
        return ok

    async def user(self, rid: int) -> None:
        """The user's side: send the request with a deadline, wait until then, then give up."""
        start = now()
        task = self.send(0, rid, start + USER_DEADLINE)
        try:
            async with asyncio.timeout(USER_DEADLINE):
                ok = await asyncio.shield(task)
            outcome = OK if ok else FAILED
        except TimeoutError:
            outcome = GAVE_UP
        end = now()
        self.ended[rid] = end
        self.requests.append((rid, start, end, outcome))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for rid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.user(rid))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            k = HOPS.index(inc.kind)
            self.cost[k] = inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.cost[k] = WORK[k]

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 40.0, connections: int = 3) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate, connections)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.holding.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            for rid in [r for r, t in s.ended.items() if t < b - STUCK]:
                del s.ended[rid]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "work": s.take(s.work, 0, a, b),
                    "calls": s.take(s.calls, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
