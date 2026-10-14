"""Lab database_index: one endless run on virtual time, handed out a minute at a time.

A `users` table starts with 20,000 rows and keeps growing (~5 signups/s). Users log in
(`find_by_email`, ~`rate`/s) and dashboards ask for the signups of a country in a time range
(`signups_between`, ~2/s). Every query runs on one of 4 database workers; it costs a fixed
overhead plus a little time per row it reads, so a full scan gets slower as the table grows.
A user gives up after waiting 2 s for a worker. Every answer is checked: a wrong one is a
failed query.

Incidents come at random, like in production: a bulk import (10,000-20,000 old rows in a few
seconds), a new report that runs many large range queries, or a spike of logins. The first
one is always an import at 0:20.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.database_index import lab
from labs.database_index.storage import Heap, Row

LAB = "database_index"
NAMES = ("Table",)
PIECE = 60.0
DRAIN = 5.0
PRELOAD = 20_000
SIGNUPS = 5.0  # per second
RANGES = 2.0  # range queries per second, when calm
COUNTRIES = ("US", "IN", "BR", "GB", "DE", "FR", "MX", "ES", "JP", "CA",
             "AR", "CO", "IT", "NG", "PH", "AU", "CL", "PE", "PL", "NL")
DAY = 86_400.0

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 27.0, "import", 15_000, "partner_import")
KINDS = [
    Kind("import", 0.35, median=7.0, shortest=5.0, longest=12.0, severity=(10_000, 20_000),
         causes=("partner_import", "backfill", "csv_upload")),
    Kind("report", 0.35, median=15.0, shortest=10.0, longest=30.0, severity=(6.0, 10.0),
         causes=("new_dashboard", "finance_export", "ad_hoc_query")),
    Kind("spike", 0.30, median=12.0, shortest=8.0, longest=25.0, severity=(2.5, 4.0),
         causes=("newsletter", "login_storm", "app_release")),
]
MEAN_GAP = 30.0
QUIET = 22.0  # at least this calm after an incident: 15 s measured before the next one

# Query kinds.
LOOKUP, RANGE, INSERT = 0, 1, 2


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.rng = random.Random(seed * 13 + 7)
        self.heap = Heap()
        self.table = code.Table(self.heap)
        self.sem: asyncio.Semaphore | None = None
        self.next_id = 0
        self.queries: list[tuple] = []  # logins and ranges: (start, id, kind, rows read, rows returned, end, ok, ran)
        self.writes: list[tuple] = []  # inserts, the same columns
        self.sizes: list[tuple] = []  # (time, rows in the table)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.lookup_boost = 1.0
        self.range_boost = 1.0
        self.report = False
        self._qids = itertools.count()

    def new_row(self, t: float) -> Row:
        rid = self.next_id
        self.next_id += 1
        country = COUNTRIES[min(len(COUNTRIES) - 1, int(self.rng.expovariate(1 / 4)))]
        return Row(rid, f"user{rid}@example.com", country, t)

    def preload(self) -> None:
        for _ in range(PRELOAD):
            self.table.insert(self.new_row(-self.rng.uniform(0, DAY)))

    # ---- one query on a database worker

    async def query(self, kind: int, qid: int, fn, check) -> None:
        start = now()
        try:
            async with asyncio.timeout(lab.TIMEOUT):
                await self.sem.acquire()
        except TimeoutError:
            self._done(kind, (start, qid, kind, 0, 0, now(), False, False))
            return
        try:
            before = self.heap.reads
            try:
                result = fn()
                read = self.heap.reads - before
                returned, ok = check(result)
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return
            await asyncio.sleep(lab.OVERHEAD + read * lab.ROW_COST)
        finally:
            self.sem.release()
        self._done(kind, (start, qid, kind, read, returned, now(), ok, True))

    def _done(self, kind: int, row: tuple) -> None:
        (self.writes if kind == INSERT else self.queries).append(row)

    def lookup(self) -> None:
        if self.next_id == 0:
            return
        target = self.rng.randrange(self.next_id)
        email = f"user{target}@example.com"

        def check(row):
            return (1 if row is not None else 0), (row is not None and row.email == email)

        qid = self._qid()
        asyncio.ensure_future(self.query(LOOKUP, qid, lambda: self.table.find_by_email(email), check))

    def range_query(self) -> None:
        country = COUNTRIES[min(len(COUNTRIES) - 1, int(self.rng.expovariate(1 / 4)))]
        window = self.rng.uniform(600, 3600) if self.report else self.rng.uniform(60, 600)
        end = now()
        start = end - window

        def check(rows):
            rows = list(rows or [])
            right = (len(rows) == self.heap.truth_range(country, start, end)
                     and all(r.country == country and start <= r.time < end for r in rows))
            return len(rows), right

        qid = self._qid()
        asyncio.ensure_future(self.query(RANGE, qid, lambda: self.table.signups_between(country, start, end),
                                         check))

    def insert(self, t: float) -> None:
        row = self.new_row(t)
        qid = self._qid()
        asyncio.ensure_future(self.query(INSERT, qid, lambda: self.table.insert(row), lambda _: (0, True)))

    def _qid(self) -> int:
        return next(self._qids)

    # ---- the traffic

    async def logins(self) -> None:
        rng = random.Random(self.seed * 13 + 1)
        t = 0.0
        while True:
            t += rng.expovariate(self.rate * self.lookup_boost)
            await asyncio.sleep(max(0.0, t - now()))
            self.lookup()

    async def ranges(self) -> None:
        rng = random.Random(self.seed * 13 + 2)
        t = 0.0
        while True:
            t += rng.expovariate(RANGES * self.range_boost)
            await asyncio.sleep(max(0.0, t - now()))
            self.range_query()

    async def signups(self) -> None:
        rng = random.Random(self.seed * 13 + 3)
        for t in arrivals(SIGNUPS, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            self.insert(now())

    async def sizes_every_second(self) -> None:
        while True:
            self.sizes.append((now(), len(self.heap)))
            await asyncio.sleep(1.0)

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "import":
                    rows = int(inc.severity)
                    gap = (inc.t1 - inc.t0) / rows
                    for _ in range(rows):
                        self.insert(now() - self.rng.uniform(0, DAY))
                        await asyncio.sleep(gap)
                case "report":
                    self.report, self.range_boost = True, inc.severity
                case "spike":
                    self.lookup_boost = inc.severity
            await asyncio.sleep(max(0.0, inc.t1 - now()))
            self.report, self.range_boost, self.lookup_boost = False, 1.0, 1.0


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 30.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)

    async def boot() -> None:
        s.sem = asyncio.Semaphore(lab.WORKERS)
        s.preload()

    sim.spawn(boot())
    for coro in (s.logins(), s.ranges(), s.signups(), s.sizes_every_second(), s.chaos()):
        sim.spawn(coro)
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
                    # (start, id, kind, rows read, rows returned, end, ok, ran); ran is False when the
                    # user gave up waiting for a worker
                    "queries": _take(s.queries, 0, a, b),
                    "writes": _take(s.writes, 0, a, b),
                    # (time, rows in the table)
                    "size": _take(s.sizes, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 30.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
