"""Lab optimistic_locking: one endless run on virtual time, handed out a minute at a time.

Users buy ~`rate` times a second through three app servers, each with its own `StockService`
over one shared database. Each request changes one item's stock by `delta`: a sale takes 1-3
units. A few items are popular, most are not, so two requests rarely touch the same row at once.
A user waits up to 1 s for an answer; a 409 (`Conflict`) is an error page.

Incidents come at random, like in production: a flash sale (traffic jumps and most of it buys
the same item), a bulk import (a job restocks the popular items while users buy them), or a
slow network (every round trip to the database is several times slower, which widens the gap
between a request's read and its write). The first incident is always a flash sale at 0:20-0:30.

The run never restarts: the stock table and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, rate_at, schedule
from core.vtime import VirtualRun, now
from labs.optimistic_locking.api import CONFLICT as CONFLICT_WRITE, Conflict, Database, current_request

LAB = "optimistic_locking"
NAMES = ("StockService", "backoff")
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a request still running after this long is a bug
APPS = 3  # app servers, each with its own StockService
ITEMS = 300  # rows in the stock table; low ids are the popular ones
POPULAR = 10  # the items a bulk import restocks
TIMEOUT = 1.0  # a user waits this long for an answer
LATENCY = 0.003  # one round trip to the database
HOT_SHARE = 0.6  # of the traffic during a flash sale, the share that buys the sale item

# Request outcomes, from the client's side.
OK, CONFLICT, TIMEOUT_, ERROR = range(4)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "flash", 3.0, "flash_sale")
KINDS = [
    Kind("flash", 0.4, median=10.0, shortest=5.0, longest=20.0, severity=(2.0, 3.5),
         causes=("flash_sale", "push_alert", "influencer", "price_error")),
    Kind("import", 0.3, median=12.0, shortest=6.0, longest=25.0, severity=(80.0, 200.0),
         causes=("supplier_feed", "recount", "price_sync")),
    Kind("slow", 0.3, median=10.0, shortest=5.0, longest=20.0, severity=(0.02, 0.06),
         causes=("cross_az", "packet_loss", "db_cpu", "noisy_neighbour")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: 15 s of baseline before the next + time to judge


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 11 + 3)
        self.db = Database(LATENCY, random.Random(seed * 11 + 1), self.on_write)
        self.apps = [code.StockService(self.db, random.Random(seed * 11 + 5 + k)) for k in range(APPS)]
        self.boost = 1.0  # traffic multiplier (a flash sale)
        self.hot: int | None = None  # the flash sale's item
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, dict] = {}  # running requests
        self.ids = itertools.count()
        self.requests: list[tuple] = []  # (id, start, end, ok, outcome, tries, lost, app, batch, hot)
        self.writes: list[tuple] = []  # (start, request, n, end, result, app)

    # ---- the database tells us about every write

    def on_write(self, who: tuple[int, int] | None, started: float, result: int, lost: int) -> None:
        if who is None or who[0] not in self.open:
            return
        r = self.open[who[0]]
        r["writes"] += 1
        r["lost"] += lost
        self.writes.append((started, who[0], r["writes"] - 1, now(), result, r["app"]))
        if result != CONFLICT_WRITE:  # written (a commit or a clobber)
            r["commits"] += 1

    # ---- clients

    def item(self, rng: random.Random) -> int:
        return int(ITEMS * rng.random() ** 2)  # skewed: a few popular items, a long tail

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11)
        t = 0.0
        while True:
            # Arrivals at the drifting base rate, thinned up to the flash sale's boost.
            t += rng.expovariate(self.rate * 4.0)
            await asyncio.sleep(t - now())
            if rng.random() * self.rate * 4.0 > rate_at(self.rate, t, self.seed) * self.boost:
                continue
            hot = self.hot is not None and rng.random() < HOT_SHARE
            item = self.hot if hot else self.item(rng)
            asyncio.ensure_future(self.request(item, -rng.randint(1, 3), False, hot, rng))

    async def bulk(self, rate: float, until: float) -> None:
        rng = random.Random(self.seed * 13 + int(now()))
        t = now()
        while True:
            t += rng.expovariate(rate)
            if t >= until:
                return
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.request(rng.randrange(POPULAR), rng.randint(5, 50), True, False, rng))

    async def request(self, item: int, delta: int, batch: bool, hot: bool, rng: random.Random) -> None:
        rid = next(self.ids)
        app = rid % APPS
        r = {"start": now(), "writes": 0, "commits": 0, "lost": 0, "app": app}
        self.open[rid] = r
        token = current_request.set((rid, delta))
        try:
            await self.apps[app].adjust(item, delta)
            outcome = OK
        except Conflict:
            outcome = CONFLICT
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            outcome = ERROR
        finally:
            current_request.reset(token)
        if outcome == OK and r["commits"] == 0:
            r["lost"] += 1  # it said yes, but its update never reached the database
        elif r["commits"] > 1:
            r["lost"] += r["commits"] - 1  # applied more than once: the stock is wrong too
        end = now()
        if end - r["start"] > TIMEOUT:
            outcome, end = TIMEOUT_, r["start"] + TIMEOUT  # the user gave up waiting
        del self.open[rid]
        self.db.seen.pop(rid, None)
        self.requests.append((rid, r["start"], end, outcome == OK, outcome, r["writes"], r["lost"], app, batch, hot))

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "flash":
                    self.boost, self.hot = inc.severity, self.rng.randrange(ITEMS)
                case "import":
                    asyncio.ensure_future(self.bulk(inc.severity, inc.t1))
                case "slow":
                    self.db.latency = inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.boost, self.hot, self.db.latency = 1.0, None, LATENCY

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 50.0) -> Iterator[dict]:
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
            if any(r["start"] < b + DRAIN - STUCK for r in s.open.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, ok, outcome, tries, updates lost, app, batch, hot item)
                    "requests": s.take(s.requests, 1, a, b),
                    # (start, request, n, end, result, app)
                    "writes": s.take(s.writes, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 50.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
