"""Lab retry_storm: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (Poisson, drifting slowly like real traffic)
through your `Client` to our service. Incidents come at random, like in
production: full outages (every call fails fast) and partial outages (a share
of calls fail). The first incident is always a full outage at 0:20-0:30.

The run never restarts: the retry budget, the service and the clock carry on
from one minute to the next, and incidents can span minute boundaries.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import FaultyService, ServiceError, current_request
from core.vtime import VirtualRun, now

LAB = "retry_storm"
NAMES = ("Client", "backoff_delay", "RetryBudget")
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a request still running after this long is a bug
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "outage", 1.0, "bad_deploy")
KINDS = [
    Kind("outage", 0.6, median=9.0, shortest=4.0, longest=30.0, causes=(
        "bad_deploy", "node_crashed", "expired_cert", "config_push", "pool_exhausted")),
    Kind("errors", 0.4, median=12.0, shortest=5.0, longest=40.0, severity=(0.4, 0.85), causes=(
        "replica_died", "out_of_memory", "noisy_neighbour", "slow_dependency", "bad_canary")),
]
MEAN_GAP = 30.0  # seconds of calm between incidents, on average, on top of QUIET
QUIET = 22.0  # at least this calm after an incident: 15 s baseline + 7 s to judge


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed = seed
        self.rate = rate
        self.service = FaultyService(rng=random.Random(seed * 3 + 1))
        self.client = code.Client(self.service, rng=random.Random(seed * 3 + 2))
        self.requests: list[tuple] = []  # finished: (id, start, end, ok, calls)
        self.open: dict[int, float] = {}  # running request id -> start
        self.starts: dict[tuple, float] = {}  # (request, attempt) -> call start
        self.calls: list[tuple] = []  # finished: (start, request, attempt, ok, end)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    async def user(self, rid: int) -> None:
        current_request.set(rid)
        start = now()
        self.open[rid] = start
        try:
            await self.client.call(rid)
            ok = True
        except ServiceError:
            ok = False
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        self.requests.append((rid, start, now(), ok, self.service.forget(rid)))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 3)
        for rid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.user(rid))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "outage":
                self.service.set_down(True)
            else:
                self.service.set_error_rate(inc.severity)
            await asyncio.sleep(inc.t1 - now())
            self.service.set_down(False)
            self.service.set_error_rate(0.0)

    def collect_calls(self) -> None:
        events = self.service.events
        for e in events:
            if e.kind == "call":
                self.starts[(e.request, e.attempt)] = e.t
            else:
                start = self.starts.pop((e.request, e.attempt))
                self.calls.append((start, e.request, e.attempt, e.kind == "ok", e.t))
        events.clear()

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
            stuck = [t for t in s.open.values() if t < b + DRAIN - STUCK]
            if stuck:
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            s.collect_calls()
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, ok, calls made)
                    "requests": s.take(s.requests, 1, a, b),
                    # (start, request id, attempt, ok, end)
                    "calls": s.take(s.calls, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 100.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
