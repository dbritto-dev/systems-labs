"""Lab keyset_pagination: one endless run on virtual time, handed out a minute at a time.

A feed of ~40,000 posts, newest first, served 20 to a page by three API servers, each with its own
`FeedAPI` over one database. ~`rate` people a second open the feed and scroll 1-8 pages, a page
every 0.5-2.5 s; a search indexer walks the whole feed, page after page, and starts again from the
top when it reaches the end. Meanwhile ~4 posts a second are written at the top, and ~0.5 a second
are deleted (mostly recent ones).

Every page is checked against the truth: a post that existed when the client started walking, and
still exists, must come exactly once. A page that repeats a post counts duplicates; a page that
jumps past posts it should have shown counts them as skipped.

Incidents come at random, like in production: a bulk import (hundreds of posts written with one
created_at: one transaction, one now()), a viral moment (posts pour in at the top, and twice the
readers), a spam cleanup (moderation deletes hundreds of recent posts a second), or sync jobs (an
export or a reindex walks the whole feed at full speed: deep pages). The first incident is always a
bulk import at 0:20-0:30.

The run never restarts: the table and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from bisect import bisect_left, insort
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, rate_at, schedule
from core.vtime import VirtualRun, now
from labs.keyset_pagination.api import (
    EPOCH_MS, PAGE_SIZE, BadCursor, Database, Post, created_ms, current_page,
)

LAB = "keyset_pagination"
NAMES = ("FeedAPI", "encode_cursor", "decode_cursor")
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a page still running after this long is a bug
APIS = 3  # API servers, each with its own FeedAPI
INITIAL = 40_000  # posts in the table at 0:00
POSTS = 4.0  # new posts a second, normally
DELETES = 0.5  # deleted posts a second, normally
RECENT = 3_000  # deletes pick among this many newest posts
MAX_PAGES = 8  # a reader scrolls at most this many pages
THINK = (0.5, 2.5)  # seconds a reader looks at a page before the next
SYNC_THINK = 0.05  # seconds a sync job waits between pages
SYNC_REST = 2.0  # seconds the indexer rests between two walks
STALLED = 3  # a sync job gives up a walk after this many pages with nothing new

# Who asked, and what came back.
READER, SYNC = range(2)
BAD, OK = range(2)  # a 400 (BadCursor: the client starts again from the top); a page

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "import", 600.0, "txn_now")
KINDS = [
    Kind("import", 0.25, median=10.0, shortest=6.0, longest=20.0, severity=(300.0, 1000.0),
         causes=("txn_now", "csv_import", "migration", "seed_job")),
    Kind("viral", 0.25, median=12.0, shortest=6.0, longest=25.0, severity=(40.0, 120.0),
         causes=("breaking_news", "match_final", "trending", "celebrity")),
    Kind("cleanup", 0.25, median=10.0, shortest=5.0, longest=20.0, severity=(100.0, 300.0),
         causes=("spam_wave", "bot_ban", "erasure", "takedown")),
    Kind("sync", 0.25, median=15.0, shortest=8.0, longest=30.0, severity=(4.0, 8.0),
         causes=("reindex", "partner_export", "warehouse", "app_release")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: 15 s of baseline before the next + time to judge


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def initial_posts(seed: int) -> list[Post]:
    """The feed at 0:00: a post every 1-3 s for the last day or so, oldest first."""
    rng = random.Random(seed * 23 + 7)
    t, out = EPOCH_MS, []
    for k in range(INITIAL):
        t -= rng.randint(1_000, 3_000)
        out.append(Post(INITIAL - k, t))
    return out[::-1]


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 11 + 3)
        posts = initial_posts(seed)
        self.db = Database(posts)
        self.apis = [code.FeedAPI(self.db) for _ in range(APIS)]
        self.ids = itertools.count(INITIAL + 1)  # post ids
        # Every post ever, deleted ones too, to check pages against: (created_at, id), oldest first.
        self.history: list[tuple[int, int]] = [(p.created_at, p.id) for p in posts]
        self.born: dict[int, float] = {}  # post id -> when it was written (missing: before 0:00)
        self.died: dict[int, float] = {}  # post id -> when it was deleted
        self.readers = 1.0  # reader traffic multiplier (a viral moment)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, float] = {}  # running pages -> start
        self.pids = itertools.count()
        self.sids = itertools.count()
        self.pages: list[tuple] = []  # see stream()
        self.writes: dict[int, list[int]] = {}  # tenth of a second -> [inserts, deletes, tied]

    # ---- the rest of the app writes and deletes posts

    def _count(self, col: int) -> None:
        self.writes.setdefault(int(now() * 10), [0, 0, 0])[col] += 1

    def insert(self, created: int | None = None) -> None:
        post = Post(next(self.ids), created_ms(now()) if created is None else created)
        self.db.insert(post)
        insort(self.history, (post.created_at, post.id))
        self.born[post.id] = now()
        self._count(0 if created is None else 2)

    def delete(self, rng: random.Random) -> None:
        recent = self.db.newest(RECENT)
        if recent:
            _, pid = recent[min(len(recent) - 1, int(len(recent) * (1 - rng.random() ** 2)))]  # newer: likelier
            if self.db.delete(pid):
                self.died[pid] = now()
                self._count(1)

    async def every(self, rate: float, action, until: float = math.inf, salt: int = 0) -> None:
        rng = random.Random(self.seed * 29 + salt + int(now()))
        while True:
            await asyncio.sleep(rng.expovariate(rate))
            if now() >= until:
                return
            action(rng)

    # ---- clients

    async def walk(self, kind: int, pages: int, rng: random.Random) -> None:
        """One client paging through the feed from the top: a reader scrolling, or a sync job."""
        sid, start = next(self.sids), now()
        seen: set[int] = set()
        low: tuple[int, int] | None = None  # the oldest post it has been shown
        cursor, depth, stalled = None, 0, 0
        for n in range(pages):
            pid = next(self.pids)
            page = {"id": pid, "read": 0, "queries": 0}
            asked = now()
            self.open[pid] = asked
            token = current_page.set(page)
            try:
                items, cursor = await self.apis[pid % APIS].list_posts(cursor)
                outcome = OK
            except BadCursor:
                items, cursor, outcome = [], None, BAD
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return
            finally:
                current_page.reset(token)
                del self.open[pid]
            dup = sum(p.id in seen for p in items)
            seen.update(p.id for p in items)
            skipped = 0
            if items:
                bottom = min((p.created_at, p.id) for p in items)
                if low is None or bottom < low:
                    skipped = self.skipped(bottom, low, start, seen)
                    low = bottom
            self.pages.append((asked, pid, now(), sid, depth, kind, page["read"], len(items), skipped, dup,
                               outcome, pid % APIS))
            depth = 0 if outcome == BAD else depth + 1
            stalled = stalled + 1 if items and dup == len(items) else 0
            if (cursor is None and outcome == OK) or stalled >= STALLED:
                return  # the end of the feed (or a job that keeps getting the same page)
            await asyncio.sleep(SYNC_THINK if kind == SYNC else rng.uniform(*THINK))

    def skipped(self, bottom: tuple[int, int], low: tuple[int, int] | None, start: float, seen: set[int]) -> int:
        """Posts between `bottom` and `low` (the part of the feed this page moved past) that existed
        when the walk started, still exist, and were never shown."""
        a = bisect_left(self.history, bottom)
        b = len(self.history) if low is None else bisect_left(self.history, low)
        t, n = now(), 0
        for _, pid in self.history[a:b]:
            if pid not in seen and self.born.get(pid, -1.0) <= start and self.died.get(pid, math.inf) > t:
                n += 1
        return n

    async def scrolling(self) -> None:
        rng = random.Random(self.seed * 11)
        t = 0.0
        top = self.rate * 3.0
        while True:
            t += rng.expovariate(top)
            await asyncio.sleep(t - now())
            if rng.random() * top > rate_at(self.rate, t, self.seed) * self.readers:
                continue
            pages = min(MAX_PAGES, 1 + int(rng.expovariate(0.5)))
            asyncio.ensure_future(self.walk(READER, pages, random.Random(rng.random())))

    async def indexer(self, until: float = math.inf, salt: int = 0) -> None:
        """A sync job: walks the whole feed, page after page; the search indexer starts over."""
        rng = random.Random(self.seed * 31 + salt)
        while now() < until:
            walk = asyncio.ensure_future(self.walk(SYNC, 10 * INITIAL // PAGE_SIZE, rng))
            while not walk.done():
                if now() >= until:
                    walk.cancel()
                    return
                await asyncio.sleep(0.5)
            await asyncio.sleep(SYNC_REST)

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "import":  # every row stamped with the same created_at: the transaction's now()
                    stamp = created_ms(inc.t0)
                    asyncio.ensure_future(self.every(inc.severity / max(1.0, inc.t1 - inc.t0),
                                                     lambda rng: self.insert(stamp), inc.t1, 1))
                case "viral":
                    self.readers = 2.0
                    asyncio.ensure_future(self.every(inc.severity, lambda rng: self.insert(), inc.t1, 2))
                case "cleanup":
                    asyncio.ensure_future(self.every(inc.severity, self.delete, inc.t1, 3))
                case "sync":
                    for k in range(int(inc.severity)):
                        asyncio.ensure_future(self.indexer(inc.t1, 100 + k))
            await asyncio.sleep(inc.t1 - now())
            self.readers = 1.0

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]

    def take_writes(self, a: float, b: float) -> list[tuple]:
        out = [(k / 10, *v, len(self.db)) for k, v in sorted(self.writes.items()) if k < b * 10]
        for k in [k for k in self.writes if k < b * 10]:
            del self.writes[k]
        return [r for r in out if r[0] >= a]


def stream(variant="main", seed: int = 1, rate: float = 10.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.scrolling())
    sim.spawn(s.indexer())
    sim.spawn(s.every(POSTS, lambda rng: s.insert(), salt=4))
    sim.spawn(s.every(DELETES, s.delete, salt=5))
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
                    # (start, id, end, walk, depth, kind, rows read, returned, skipped, duplicates,
                    #  outcome, api server)
                    "pages": s.take(s.pages, 0, a, b),
                    # (start, end, rows read, worker, page id): every query the database ran
                    "queries": s.take(s.db.busy, 0, a, b),
                    # (t, inserts, deletes, imported with one created_at, posts in the table): per 0.1 s
                    "writes": s.take_writes(a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 10.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
