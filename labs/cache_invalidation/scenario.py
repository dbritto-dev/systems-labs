"""Lab cache_invalidation: one endless run on virtual time, handed out a minute at a time.

Users open ~`rate` product pages a second through three app servers, each with its own
`ProductCache` over one shared cache and one database. Popularity is skewed: a few products get most
of the views. Checkouts write the stock of the products they sell (~5 writes/s). Every app server
stops now and then for a garbage-collection pause, and a few replies take much longer than the rest:
a request that loaded a record can store it in the cache a long time later.

Incidents come at random, like in production: a price campaign (a repricing job rewrites the prices
of the popular products many times a second, and some writes hit lock timeouts), an import (a job
rewrites the whole catalogue, and some rows break a constraint), a slow network (every round trip
takes several times longer, which widens every race), or a cache node restart (it answers nothing
for a few seconds and comes back empty). The first incident is always a price campaign at 0:20-0:30.

The run never restarts: the cache, the database and the clock carry on from one minute to the next.
It starts warm (it runs 30 s before 0:00).
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_left, bisect_right
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.cache_invalidation.api import (
    Cache, CacheClient, Database, DatabaseClient, Record, Server, WriteFailed, current_request,
)

LAB = "cache_invalidation"
NAMES = ("ProductCache", "TTL")
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 20.0  # a request still running after this long is a bug
WARMUP = 30.0
APPS = 3
KEYS = 1000  # products; low keys are the popular ones
SKEW = 1.0  # Zipf exponent of their popularity
HOT = 100  # the products a price campaign reprices
CHECKOUTS = 5.0  # stock writes a second, all day
GRACE = 0.5  # seconds: a read that starts this long after a write was acknowledged must see it
PAUSE_GAP = 1.0  # mean seconds between one app server's GC pauses
PAUSE = (0.03, 0.15)  # seconds a pause lasts
FOLLOW = (0.005, 0.06)  # seconds between a campaign's two writes to one product
FAIL = {"": 0.01, "campaign": 0.05, "import": 0.04}  # writes the database refuses

# Where a write came from.
CHECKOUT, CAMPAIGN, IMPORT = range(3)
# What a read returned.
FRESH, STALE, PHANTOM = range(3)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "campaign", 80.0, "flash_prices")
KINDS = [
    Kind("campaign", 0.3, median=10.0, shortest=6.0, longest=20.0, severity=(50.0, 100.0),
         causes=("flash_prices", "repricing_bot", "currency", "black_friday")),
    Kind("import", 0.25, median=12.0, shortest=6.0, longest=25.0, severity=(100.0, 250.0),
         causes=("supplier_feed", "catalog_sync", "erp_export")),
    Kind("slow", 0.25, median=10.0, shortest=5.0, longest=20.0, severity=(4.0, 10.0),
         causes=("cross_az", "packet_loss", "noisy_neighbour")),
    Kind("restart", 0.2, median=2.0, shortest=1.0, longest=4.0,
         causes=("oom_kill", "kernel_update", "cache_deploy")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: 5 s to check the cache, 15 s of baseline before the next


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.rng = random.Random(seed * 13 + 1)
        self.cum = list(itertools.accumulate(1.0 / (k ** SKEW) for k in range(1, KEYS + 1)))
        self.db = Database(KEYS, random.Random(seed * 13 + 2))
        self.db.fail = FAIL[""]
        self.cache = Cache(random.Random(seed * 13 + 3), self.on_fill, self.db)
        self.servers = [Server() for _ in range(APPS)]
        self.apps = [code.ProductCache(CacheClient(self.cache, s), DatabaseClient(self.db, s)) for s in self.servers]
        self.ids = itertools.count()
        self.wids = itertools.count(1)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, float] = {}  # running request id -> start
        self.acks: dict[int, tuple[list[float], list[int]]] = {}  # key -> (ack times, newest index acked by then)
        self.raw: list[tuple] = []  # reads, not yet judged
        self.reads: list[tuple] = []  # (id, start, end, app, key, missed, verdict, fresh)
        self.writes: list[tuple] = []  # (start, end, app, key, ok, source)
        self.fills: list[tuple] = []  # (t, app, key, result)
        self.pauses: list[tuple] = []  # (t0, t1, app)
        self.audit: list[tuple] = []  # (t, stale entries, entries, db reads in the last second, cache up)

    def key(self, rng: random.Random) -> int:
        return min(KEYS - 1, bisect_left(self.cum, rng.random() * self.cum[-1]))

    def on_fill(self, key: int, record: Record, result: int) -> None:
        req = current_request.get()
        self.fills.append((now(), req["app"], key, result))

    # ---- users read

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 13)
        for t in arrivals(self.rate, self.seed, -WARMUP, rng):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.read(self.key(rng)))

    async def read(self, key: int) -> None:
        rid = next(self.ids)
        app = rid % APPS
        req = {"db": 0, "write": False, "app": app}
        start = self.open[rid] = now()
        current_request.set(req)  # each request runs in its own task, with its own context
        try:
            record = await self.apps[app].read(key)
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        if not isinstance(record, Record):
            self.bugs.append(TypeError(lab_text(LAB).STRINGS["bad_read"].format(value=repr(record)[:40])))
            return
        if start >= 0:
            self.raw.append((rid, start, now(), app, key, req["db"] > 0, record))

    def judge(self, r: tuple) -> tuple:
        """Fresh, stale (older than a write acknowledged before the read started) or never saved."""
        rid, start, end, app, key, missed, record = r
        verdict = FRESH
        if self.db.phantom(record):
            verdict = PHANTOM
        elif record.write in self.db.index:
            times, newest = self.acks.get(key, ((), ()))
            i = bisect_right(times, start - GRACE)
            if i and self.db.index[record.write] < newest[i - 1]:
                verdict = STALE
        return rid, start, end, app, key, missed, verdict, verdict == FRESH

    def forget(self, before: float) -> None:
        """Every read still to be judged starts after `before`, and the cache and the checker only ask
        about now: forget the acks and commit times older than that (keeping the last one before it,
        which is what a read starting just after `before` is judged against)."""
        self.db.forget(before)
        for times, newest in self.acks.values():
            i = bisect_right(times, before) - 1
            if i > 0:
                del times[:i], newest[:i]

    # ---- writers

    async def writer(self, rate: float, until: float, source: int, keys) -> None:
        rng = random.Random(self.seed * 17 + int(now()) * 3 + source)
        t = now()
        while True:
            t += rng.expovariate(rate)
            if t >= until:
                return
            await asyncio.sleep(t - now())
            key = keys(rng)
            asyncio.ensure_future(self.write(key, source, rng))
            if source == CAMPAIGN:  # the sale price follows the price, from another worker
                asyncio.ensure_future(self.write(key, source, rng, rng.uniform(*FOLLOW)))

    async def write(self, key: int, source: int, rng: random.Random, after: float = 0.0) -> None:
        if after:
            await asyncio.sleep(after)
        rid = next(self.ids)
        app = rid % APPS
        old = self.db.rows[key]
        if source == CHECKOUT:
            record = Record(old.price, max(0, old.stock - rng.randint(1, 3)), next(self.wids))
        elif source == CAMPAIGN:
            record = Record(max(99, old.price + rng.choice((-1, 1)) * rng.randint(10, 300)), old.stock, next(self.wids))
        else:
            record = Record(old.price + rng.randint(-50, 50), rng.randint(0, 200), next(self.wids))
        start = self.open[rid] = now()
        current_request.set({"db": 0, "write": True, "app": app})
        ok = True
        try:
            await self.apps[app].update(key, record)
        except WriteFailed:
            ok = False
        except Exception as exc:
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        if ok and record.write in self.db.index:  # acknowledged: from now on, reads must see it
            times, newest = self.acks.setdefault(key, ([], []))
            times.append(now())
            newest.append(max(self.db.index[record.write], newest[-1] if newest else 0))
            if len(times) > 4096:  # forget acks older than any read still to be judged
                del times[:2048], newest[:2048]
        if start >= 0:
            self.writes.append((start, now(), app, key, ok, source))

    # ---- the app servers stop now and then

    async def gc(self, k: int) -> None:
        rng = random.Random(self.seed * 19 + k)
        while True:
            await asyncio.sleep(rng.expovariate(1.0 / PAUSE_GAP))
            t0 = now()
            t1 = t0 + rng.uniform(*PAUSE)
            self.servers[k].paused_until = t1
            if t0 >= 0:
                self.pauses.append((t0, t1, k))
            await asyncio.sleep(t1 - t0)

    # ---- every second: how many cache entries are stale?

    async def check(self) -> None:
        reads = self.db.reads
        while True:
            await asyncio.sleep(int(now()) + 1 - now())
            t = now()
            stale, n = self.cache.stale(self.db, t, GRACE)
            if t >= 0:
                self.audit.append((t, stale, n, self.db.reads - reads, self.cache.up))
            reads = self.db.reads

    # ---- incidents

    async def chaos(self) -> None:
        self.ensure(self.writer(CHECKOUTS, float("inf"), CHECKOUT, self.key))
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            self.db.fail = FAIL.get(inc.kind, FAIL[""])
            match inc.kind:
                case "campaign":
                    self.ensure(self.writer(inc.severity, inc.t1, CAMPAIGN, lambda rng: rng.randrange(HOT)))
                case "import":
                    self.ensure(self.writer(inc.severity, inc.t1, IMPORT, lambda rng: rng.randrange(KEYS)))
                case "slow":
                    self.db.slow = self.cache.slow = inc.severity
                case "restart":
                    self.cache.restart()
            await asyncio.sleep(inc.t1 - now())
            self.db.fail, self.db.slow, self.cache.slow = FAIL[""], 1.0, 1.0
            self.cache.back()

    def ensure(self, coro) -> None:
        asyncio.ensure_future(coro)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 300.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun(-WARMUP)
    s = _Sim(code, seed, rate)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    sim.spawn(s.check())
    for k in range(APPS):
        sim.spawn(s.gc(k))
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.open.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            s.reads.extend(s.judge(r) for r in s.take(s.raw, 1, a, b))
            s.forget(a)
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    "reads": s.take(s.reads, 1, a, b),  # (id, start, end, app, key, missed, verdict, fresh)
                    "writes": s.take(s.writes, 0, a, b),  # (start, end, app, key, ok, source)
                    "fills": s.take(s.fills, 0, a, b),  # (t, app, key, result)
                    "pauses": s.take(s.pauses, 0, a, b),  # (t0, t1, app)
                    "audit": s.take(s.audit, 0, a, b),  # (t, stale entries, entries, db reads, cache up)
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 300.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
