"""Lab n_plus_one: one endless run on virtual time, handed out a minute at a time.

Users open ~`rate` pages/s. A page lists the orders of one shop (10-30 of them) and shows
each order's customer. Your `load_page(page_id, db)` builds the page from the database,
which has four ways to ask (each one is one round trip):

    await db.fetch_orders(page_id)               the page's orders
    await db.fetch_customer(customer_id)         one customer
    await db.fetch_customers(customer_ids)       many customers at once (WHERE id IN (...))
    await db.fetch_orders_with_customers(page)   orders joined with their customers (JOIN)

A round trip costs ~2 ms plus a little per row, and the database runs 8 queries at a time;
the rest wait. Users give up on a page after 2 s.

Incidents come at random, like in production: the database gets slower per round trip (a
backup, a noisy disk, a failover to another zone), pages get much longer (a sale), or
traffic spikes. The first one is always a slow database at 0:20-0:30.

The checker counts every query, by page, and checks every page that comes back.
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

LAB = "n_plus_one"
NAMES = ("load_page",)
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0
CONNECTIONS = 8  # queries the database runs at once
ROUND_TRIP = 0.002  # seconds per query, before rows
PER_ROW = 0.00005  # seconds per row returned
JOIN_PER_ROW = 0.00007  # a join costs a little more per row
GIVE_UP = 2.0  # users leave a page after this long
SAMPLE = 4  # queries of every SAMPLE-th page are kept for the picture
CUSTOMERS = 5000
ITEMS = (10, 30)  # orders on a page

# Query kinds.
LIST, ONE, MANY, JOIN = range(4)

FIRST = Planned(20.0, 30.0, "slow_db", 20.0, "backup")
KINDS = [
    Kind("slow_db", 0.4, median=10.0, shortest=6.0, longest=20.0, severity=(20.0, 30.0), causes=(
        "backup", "noisy_disk", "zone_failover", "vacuum")),
    Kind("big_pages", 0.35, median=12.0, shortest=6.0, longest=25.0, severity=(4.0, 6.0), causes=(
        "flash_sale", "bulk_import", "holiday_orders")),
    Kind("spike", 0.25, median=10.0, shortest=5.0, longest=20.0, severity=(2.0, 3.0), causes=(
        "newsletter", "tv_ad", "bot_crawl")),
]
MEAN_GAP = 30.0
QUIET = 22.0  # at least this calm after an incident: 15 s baseline + 7 s to judge


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class Database:
    """A small orders/customers database: 8 queries at a time, each one round trip."""

    def __init__(self, sim: "_Sim") -> None:
        self._sim = sim
        self._sem = asyncio.Semaphore(CONNECTIONS)
        self.extra = 0.0  # seconds added to every round trip during a slow-database incident

    def _orders(self, page_id: int) -> list[dict]:
        rng = random.Random(page_id * 7919 + 13)
        lo, hi = ITEMS
        n = rng.randint(lo, hi) * self._sim.page_scale(page_id)
        return [{"id": page_id * 1000 + i, "customer_id": rng.randrange(CUSTOMERS)} for i in range(n)]

    @staticmethod
    def _customer(cid: int) -> dict:
        return {"id": cid, "name": f"customer {cid}"}

    async def _run(self, kind: int, rows: int, per_row: float = PER_ROW) -> None:
        page = current_request.get()
        queued = now()
        async with self._sem:
            start = now()
            self._sim.busy += 1
            try:
                await asyncio.sleep(ROUND_TRIP + self.extra + rows * per_row)
            finally:
                self._sim.busy -= 1
        self._sim.record_query(page, kind, queued, start, now())

    async def fetch_orders(self, page_id: int) -> list[dict]:
        """SELECT * FROM orders WHERE page = ?"""
        orders = self._orders(page_id)
        await self._run(LIST, len(orders))
        return [dict(o) for o in orders]

    async def fetch_customer(self, customer_id: int) -> dict:
        """SELECT * FROM customers WHERE id = ?"""
        await self._run(ONE, 1)
        return self._customer(customer_id)

    async def fetch_customers(self, customer_ids) -> dict[int, dict]:
        """SELECT * FROM customers WHERE id IN (...): {id: customer}"""
        ids = set(customer_ids)
        await self._run(MANY, len(ids))
        return {cid: self._customer(cid) for cid in ids}

    async def fetch_orders_with_customers(self, page_id: int) -> list[tuple[dict, dict]]:
        """SELECT * FROM orders JOIN customers ON ... WHERE page = ?: [(order, customer)]"""
        orders = self._orders(page_id)
        await self._run(JOIN, len(orders), JOIN_PER_ROW)
        return [(dict(o), self._customer(o["customer_id"])) for o in orders]


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate, self.code = seed, rate, code
        self.db = Database(self)
        self.busy = 0
        self.scale = 1  # page length multiplier (big_pages incident)
        self.scaled: dict[int, int] = {}  # page id -> its multiplier, fixed when it starts
        self.pages: list[tuple] = []  # finished: (id, start, end, ok, items, queries)
        self.queries: list[tuple] = []  # sampled: (queued, page, kind, started, ended)
        self.counts: dict[int, int] = {}  # page id -> queries so far
        self.secs: dict[int, list[float]] = {}  # second -> [queries by kind x4, busy seconds]
        self.open: dict[int, float] = {}
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    def page_scale(self, page_id: int) -> int:
        return self.scaled.get(page_id, 1)

    def record_query(self, page: int | None, kind: int, queued: float, start: float, end: float) -> None:
        if page is not None:
            self.counts[page] = self.counts.get(page, 0) + 1
            if page % SAMPLE == 0:
                self.queries.append((queued, page, kind, start, end))
        self.secs.setdefault(int(queued), [0.0] * 5)[kind] += 1  # asked for in this second
        self.secs.setdefault(int(start), [0.0] * 5)[4] += end - start  # ran from this second (< 1 s)

    async def user(self, page_id: int) -> None:
        current_request.set(page_id)
        self.scaled[page_id] = self.scale
        start = now()
        self.open[page_id] = start
        ok = False
        try:
            async with asyncio.timeout(GIVE_UP):
                page = await self.code.load_page(page_id, self.db)
            ok = self.correct(page_id, page)
        except TimeoutError:
            ok = False
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(page_id, None)
        expected = len(self.db._orders(page_id))
        self.pages.append((page_id, start, now(), ok, expected, self.counts.pop(page_id, 0)))
        self.scaled.pop(page_id, None)

    def correct(self, page_id: int, page) -> bool:
        """Every order of the page, each with its own customer."""
        try:
            want = {(o["id"], o["customer_id"]) for o in self.db._orders(page_id)}
            got = {(row["order"]["id"], row["customer"]["id"]) for row in page}
            return got == want and all(row["order"]["customer_id"] == row["customer"]["id"] for row in page)
        except (TypeError, KeyError):
            return False

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 5 + 1)
        for pid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.user(pid))
            if self.spike > 1:  # a spike: more pages at the same moment
                for k in range(1, int(self.spike)):
                    asyncio.ensure_future(self.user(-(pid * 10 + k)))

    spike = 1.0

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "slow_db":
                self.db.extra = inc.severity / 1000.0
            elif inc.kind == "big_pages":
                self.scale = round(inc.severity)
            else:
                self.spike = inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.db.extra, self.scale, self.spike = 0.0, 1, 1.0


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 30.0) -> Iterator[dict]:
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
            secs = sorted((float(sec), *row) for sec, row in s.secs.items() if a <= sec < b)
            for sec in [sec for sec in s.secs if sec < b]:
                del s.secs[sec]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, ok, items, queries); spike pages have negative ids
                    "pages": _take(s.pages, 1, a, b),
                    # (queued, page, kind, started, ended): every query of every SAMPLE-th page
                    "queries": _take(s.queries, 0, a, b),
                    # (second, list, one, many, join queries, busy seconds)
                    "secs": secs,
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
