"""Lab circuit_breaker: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (Poisson, drifting slowly like real traffic) to our
service. Each request waits for one of `workers` workers, then calls ONE
dependency through your `Client`: "payments" (60%) or "recs" (40%). A user gives
up after DEADLINE seconds, wherever the request is.

Incidents come at random, like in production: one dependency gets very slow
(seconds per call: a GC storm, a lock, a network brownout). The first incident
is always "recs" at 0:20-0:30, 8 s per call.

The run never restarts: the workers, your bulkheads and breakers and the clock
carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import FaultyService, ServiceError, current_request
from core.vtime import VirtualRun, now

LAB = "circuit_breaker"
NAMES = ("Client", "Bulkhead", "CircuitBreaker")
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a request still running after this long is a bug
DEADLINE = 2.0  # a user gives up after this long
DEPS = ("payments", "recs")
SHARE = (0.6, 0.4)  # of requests per dependency
LATENCY = 0.020  # a normal call
FIRST = Planned(20.0, 30.0, "recs", 8.0, "a GC storm in the recommendations service")
KINDS = [
    Kind("payments", 0.5, median=10.0, shortest=6.0, longest=25.0, severity=(4.0, 10.0), causes=(
        "a lock on the ledger table",
        "a network brownout to the payment provider",
        "a GC storm in the payments service",
        "the payment provider is rate-limiting us",
    )),
    Kind("recs", 0.5, median=10.0, shortest=6.0, longest=25.0, severity=(4.0, 10.0), causes=(
        "a GC storm in the recommendations service",
        "a cold model cache after a deploy",
        "a slow feature store",
        "a noisy neighbour on its database",
    )),
]
MEAN_GAP = 30.0
QUIET = 28.0  # at least this calm after an incident: 13 s to judge it + a 15 s baseline

# Request outcomes.
OK, FAILED, REFUSED, GAVE_UP = range(4)  # served; the call failed; refused without a call; the user left
# Call outcomes.
CALL_OK, CALL_ERROR, CALL_CUT = range(3)  # answered; error; cut short (timeout or the user left)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class Dependency:
    """What your Client calls: one dependency, recording every call it gets."""

    def __init__(self, name: str, index: int, service: FaultyService, sim: "_Sim") -> None:
        self.name, self.index, self.service, self.sim = name, index, service, sim

    async def call(self, payload=None):
        rid = current_request.get()
        start, outcome = now(), CALL_CUT
        self.sim.called.add(rid)
        try:
            result = await self.service.call(payload)
            outcome = CALL_OK
            return result
        except ServiceError:
            outcome = CALL_ERROR
            raise
        finally:
            self.sim.calls.append((start, rid, self.index, now(), outcome))
            self.service.forget(rid)


class _Sim:
    def __init__(self, code, seed: int, rate: float, workers: int) -> None:
        self.seed, self.rate = seed, rate
        self.workers = asyncio.Semaphore(workers)
        self.services = [FaultyService(name, latency=LATENCY, rng=random.Random(seed * 7 + i))
                         for i, name in enumerate(DEPS)]
        self.deps = {name: Dependency(name, i, svc, self) for i, (name, svc) in enumerate(zip(DEPS, self.services))}
        self.client = code.Client(self.deps, rng=random.Random(seed * 7 + 5))
        # (id, start, got a worker at or None, end, dependency, outcome, called it)
        self.requests: list[tuple] = []
        self.work: list[tuple] = []  # (got a worker, request id, dependency, freed it): the server side
        self.got: dict[int, float] = {}  # request id -> when it got a worker (until its row is written)
        self.holding: dict[int, float] = {}  # request id -> holding a worker since
        self.calls: list[tuple] = []  # (start, request id, dependency, end, outcome)
        self.called: set[int] = set()
        self.open: dict[int, float] = {}
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    async def serve(self, rid: int, dep: int) -> int | None:
        """The server's side: wait for a worker, call the dependency, free the worker.

        It does not know whether the user is still waiting: it carries on either way.
        """
        async with self.workers:
            got = now()
            self.got[rid] = self.holding[rid] = got
            try:
                await self.client.call(DEPS[dep], rid)
                return OK
            except (ServiceError, TimeoutError):
                return FAILED if rid in self.called else REFUSED
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return None
            finally:
                self.work.append((got, rid, dep, now()))
                self.called.discard(rid)
                del self.holding[rid]
                if rid not in self.open:  # the user already left: nobody will read it
                    self.got.pop(rid, None)

    async def user(self, rid: int, dep: int) -> None:
        """The user's side: wait up to DEADLINE for an answer, then give up."""
        current_request.set(rid)
        start = now()
        self.open[rid] = start
        work = asyncio.ensure_future(self.serve(rid, dep))
        try:
            async with asyncio.timeout(DEADLINE):
                outcome = await asyncio.shield(work)
            if outcome is None:
                return
        except TimeoutError:
            outcome = GAVE_UP
        finally:
            self.open.pop(rid, None)
        self.requests.append((rid, start, self.got.pop(rid, None), now(), dep, outcome,
                              outcome in (OK, FAILED)))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for rid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            dep = 0 if rng.random() < SHARE[0] else 1
            asyncio.ensure_future(self.user(rid, dep))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            sick = self.services[DEPS.index(inc.kind)]
            sick.set_slow(inc.severity)
            await asyncio.sleep(inc.t1 - now())
            sick.set_slow(LATENCY)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 100.0, workers: int = 24) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate, workers)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.holding.values()):
                raise RuntimeError(f"a request has been running for over {STUCK:.0f} s: "
                                   "does Client.call wait for something that never finishes?")
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "calls": s.take(s.calls, 0, a, b),
                    "work": s.take(s.work, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
