"""Lab rate_limiting: one endless run on virtual time, handed out a minute at a time.

20 clients call an API through your `RateLimiter`. Normally they send ~`rate`
requests/s together (Poisson, drifting slowly like real traffic). The backend
does 15 requests at a time, 100 ms each (150/s); beyond that requests wait in a
short queue, and a full queue rejects them (503).

Incidents come at random, like in production: some clients flood the API in
bursts (a batch job sending its work in chunks, a scraper, an SDK release with a
retry bug). The first one is always 5 clients at 0:20-0:35.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import DatabaseBusy, SlowDatabase, current_request
from core.vtime import VirtualRun, now

LAB = "rate_limiting"
NAMES = ("RateLimiter",)
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a request still running after this long is a bug
CLIENTS = 20
WORKERS = 15  # the backend: 15 requests at a time...
SERVICE_TIME = 0.100  # ...100 ms each: 150 requests/s
QUEUE = 15  # requests that may wait for a worker; more are rejected (503)
BURST_RATE = 200.0  # requests/s while a flooding client is in a burst
BURST_LENGTH = 0.3  # seconds per burst
BURST_EVERY = (0.6, 1.4)  # seconds between bursts
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 35.0, "batch", 5, "batch_first")
KINDS = [
    Kind("batch", 0.4, median=14.0, shortest=8.0, longest=30.0, severity=(3, 6), causes=(
        "batch_chunks", "nightly_export", "partner_sync")),
    Kind("scraper", 0.3, median=12.0, shortest=6.0, longest=25.0, severity=(1, 1), causes=(
        "scraper_reset", "load_test", "retry_loop")),
    Kind("sdk", 0.3, median=16.0, shortest=8.0, longest=30.0, severity=(4, 7), causes=(
        "sdk_retry_bug", "mobile_polls", "webhook_replay")),
]
MEAN_GAP = 30.0
QUIET = 22.0  # at least this calm after an incident: 15 s baseline + 7 s to judge

SERVED, LIMITED, FAILED = range(3)  # what happened to a request


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed = seed
        self.rate = rate
        self.code = code
        self.limiter = code.RateLimiter()
        self.backend = SlowDatabase(service_time=SERVICE_TIME, concurrency=WORKERS, queue_limit=QUEUE,
                                    name="api backend")
        self.rng = random.Random(seed * 7 + 3)
        self.ids = itertools.count()
        self.requests: list[tuple] = []  # finished: (id, start, end, client, outcome, flooding)
        self.open: dict[int, float] = {}
        self.planned: list[Planned] = []
        self.flooding: set[int] = set()  # clients flooding right now
        self.bugs: list[BaseException] = []

    async def request(self, client: int) -> None:
        rid = next(self.ids)
        current_request.set(rid)
        start = now()
        flooding = client in self.flooding
        self.open[rid] = start
        try:
            if not self.limiter.allow(client, start):
                outcome = LIMITED
            else:
                try:
                    await self.backend.read(rid)
                    outcome = SERVED
                except DatabaseBusy:
                    outcome = FAILED
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        self.requests.append((rid, start, now(), client, outcome, flooding))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.request(rng.randrange(CLIENTS)))

    async def flood(self, client: int, until: float, rate: float) -> None:
        """One client's bursts: BURST_LENGTH s at `rate` requests/s, every 0.6-1.4 s."""
        rng = random.Random(self.seed * 1_000 + client * 31 + int(now()))
        await asyncio.sleep(rng.uniform(0, BURST_EVERY[1]))  # each client starts at its own moment
        while now() < until:
            end = min(until, now() + BURST_LENGTH)
            while now() < end:
                asyncio.ensure_future(self.request(client))
                await asyncio.sleep(1.0 / rate)
            await asyncio.sleep(rng.uniform(*BURST_EVERY))

    async def chaos(self) -> None:
        pick = random.Random(self.seed * 7 + 5)
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            who = pick.sample(range(CLIENTS), int(inc.severity))
            rate = BURST_RATE * (2 if inc.kind == "scraper" else 1)
            self.flooding = set(who)
            for c in who:
                asyncio.ensure_future(self.flood(c, inc.t1, rate))  # each stops on its own at t1
            await asyncio.sleep(inc.t1 - now())
            self.flooding = set()

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
            s.backend.events.clear()  # not needed, and an endless run must stay small
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, client, outcome, flooding)
                    "requests": s.take(s.requests, 1, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 100.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
