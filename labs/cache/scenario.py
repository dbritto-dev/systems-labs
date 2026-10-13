"""Lab cache: one endless run on virtual time, handed out a minute at a time.

Users open ~`rate` pages/s (Poisson, drifting slowly like real traffic). Each
page reads `keys` different keys, picked with Zipf-skewed popularity (a few
keys are very hot), through your `get(key, cache=..., db=...)`. The database
takes 20 ms per read and does 8 reads at a time; beyond that reads queue, and
a full queue rejects reads. The 5 hottest keys are expensive aggregates: they
take 8x longer to build.

Incidents come at random, like deploys in production: something empties the
cache (a deploy, a restart, a failover). The first one is always at 0:20.
The run never restarts: the cache, the database queue and the clock carry on
from one minute to the next. It starts warm (a warm-up runs before 0:00).
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_left
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import DatabaseBusy, SlowDatabase, current_request
from core.vtime import VirtualRun, now

LAB = "cache"
NAMES = ("Cache", "get")
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a read still running after this long is a bug
WARMUP = 40.0
SERVICE_TIME = 0.020
CONCURRENCY = 8
QUEUE_LIMIT = 400
TTL = 30.0
HOT_KEYS = 5  # the hottest keys are expensive aggregates (a home page, a top-10 list)
HOT_COST = 8.0  # ...that take 8x longer to build than a plain read (160 ms)
FIRST = Planned(20.0, 20.0, "deploy", 1.0, "a deploy restarted the cache nodes")
KINDS = [
    Kind("deploy", 0.6, causes=("a deploy restarted the cache nodes",
                                "a config change rolled the cache cluster")),
    Kind("restart", 0.25, causes=("the cache ran out of memory and restarted",
                                  "a kernel update rebooted the cache hosts")),
    Kind("failover", 0.15, causes=("the cache failed over to an empty replica",
                                   "a network blip made the cache client reconnect to a cold node")),
]
MEAN_GAP = 35.0
QUIET = 27.0  # at least this calm after a flush: 12 s to judge it + a 15 s baseline

# Kinds of read, also the order of "extra work".
HIT, SHARED, MISS, DUP, FAILED = range(5)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def zipf_cum(n: int, s: float) -> list[float]:
    return list(itertools.accumulate(1.0 / (k ** s) for k in range(1, n + 1)))


class _Sim:
    def __init__(self, code, seed: int, rate: float, keys: int, n_keys: int, skew: float,
                 ttl: float, hot_keys: int, hot_cost: float) -> None:
        self.seed, self.rate, self.keys = seed, rate, keys
        self.cum = zipf_cum(n_keys, skew)
        self.code = code
        self.db = SlowDatabase(service_time=SERVICE_TIME, concurrency=CONCURRENCY,
                               queue_limit=QUEUE_LIMIT,
                               cost=lambda key: hot_cost if key < hot_keys else 1.0)
        self.cache = code.Cache(ttl=ttl, rng=random.Random(seed * 5 + 2))
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, float] = {}  # running page id -> start
        self.raw_reads: list[tuple] = []  # finished, not yet classified
        self.raw_pages: list[tuple] = []
        # Classified rows waiting to be handed out.
        self.pages: list[tuple] = []  # (id, start, end, ok, worst kind)
        self.reads: list[tuple] = []  # (start, page, key, end, ok, kind)
        self.loads: list[tuple] = []  # (queued, page, key, started, ended, ok, duplicate)
        # Classification state that carries on forever.
        self._opened: dict[tuple, list] = {}
        self._by_read: dict[tuple, list] = {}
        self._inflight: dict[int, int] = {}  # key -> loads queued or running
        self._worst: dict[int, int] = {}

    async def read_one(self, rid: int, key: int) -> bool:
        t0 = now()
        try:
            await self.code.get(key, cache=self.cache, db=self.db)
            ok = True
        except DatabaseBusy:
            ok = False
        self.raw_reads.append((t0, rid, key, now(), ok))
        return ok

    async def page(self, rid: int, wanted: list[int]) -> None:
        current_request.set(rid)
        t0 = now()
        self.open[rid] = t0
        try:
            oks = await asyncio.gather(*(self.read_one(rid, k) for k in wanted))
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        self.raw_pages.append((rid, t0, now(), all(oks)))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 5)
        total = self.cum[-1]
        rid, warm = 0, 0
        for t in arrivals(self.rate, self.seed, -WARMUP, rng):
            wanted: list[int] = []
            while len(wanted) < self.keys:
                k = bisect_left(self.cum, rng.random() * total)
                if k not in wanted:
                    wanted.append(k)
            await asyncio.sleep(t - now())
            if t >= 0:
                asyncio.ensure_future(self.page(rid, wanted))
                rid += 1
            else:
                warm += 1  # warm-up pages get negative ids and are not handed out
                asyncio.ensure_future(self.page(-warm, wanted))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            self.cache.clear()

    def classify(self) -> None:
        """Turn raw events into rows: which reads were hits, misses or duplicate loads."""
        for e in self.db.events:
            k = (e.request, e.key)
            match e.kind:
                case "queued":
                    # A load is a duplicate if another load of the same key is in flight.
                    busy = self._inflight.get(e.key, 0)
                    self._inflight[e.key] = busy + 1
                    row = [e.t, e.request, e.key, None, None, True, busy > 0]
                    self._opened[k] = self._by_read[k] = row
                case "reject":
                    row = [e.t, e.request, e.key, None, e.t, False, False]
                    self._by_read[k] = row
                    self.loads.append(tuple(row))
                case "start":
                    self._opened[k][3] = e.t
                case "done":
                    row = self._opened.pop(k)
                    row[4] = e.t
                    if (left := self._inflight[e.key] - 1) > 0:
                        self._inflight[e.key] = left
                    else:
                        del self._inflight[e.key]
                    self.loads.append(tuple(row))
        self.db.events.clear()
        for t0, rid, key, t1, ok in self.raw_reads:
            load_row = self._by_read.pop((rid, key), None)
            if not ok:
                kind = FAILED
            elif load_row is not None:
                kind = DUP if load_row[6] else MISS
            elif t1 - t0 < 1e-6:
                kind = HIT
            else:
                kind = SHARED
            self.reads.append((t0, rid, key, t1, ok, kind))
            self._worst[rid] = max(self._worst.get(rid, 0), kind)
        self.raw_reads.clear()
        for rid, t0, t1, ok in self.raw_pages:
            self.pages.append((rid, t0, t1, ok, self._worst.pop(rid, 0)))
        self.raw_pages.clear()

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 200.0, keys: int = 3,
           n_keys: int = 50_000, skew: float = 1.3, ttl: float = TTL,
           hot_keys: int = HOT_KEYS, hot_cost: float = HOT_COST) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun(start=-WARMUP)
    s = _Sim(code, seed, rate, keys, n_keys, skew, ttl, hot_keys, hot_cost)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.open.values()):
                raise RuntimeError(f"a read has been running for over {STUCK:.0f} s: "
                                   "does get() wait for something that never finishes?")
            s.classify()
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "pages": s.take(s.pages, 1, a, b),
                    "reads": s.take(s.reads, 0, a, b),
                    "db": s.take(s.loads, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
