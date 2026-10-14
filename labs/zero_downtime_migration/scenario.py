"""Lab zero_downtime_migration: one endless run on virtual time, handed out a minute at a time.

Six app instances serve ~`rate` requests/s (Poisson, drifting slowly like real traffic): 70%
read a user's name, 30% change it, on a random row of the `users` table (`rows` rows). Every
request goes to one instance (round robin over the ones that are up), and that instance runs
the code of its release: the old release (given below, `OldRelease`) reads and writes the old
column; the new release runs your `read_name` and `write_name`.

The database is one primary. Its load (0..1) is the app's traffic (~0.3), plus whatever else
is running: your backfill (it follows how much of the last second your copies ran), instances
that just restarted (their caches are cold for a few seconds), a traffic peak or a nightly job,
and the reads of other pages that move to the primary when the replica is out of the pool. Every statement takes its usual time over (1 - load), so near full
load everything is slow. A copy locks the rows it copies until it commits: writes to them wait.
The replica applies every changed row at APPLY rows/s; when it lags more than SHUN seconds the
proxy takes it out of the pool, and its reads land on the primary (put back below BACK_IN s).

Incidents are migration windows, at random like releases in production. Each one renames a
column of `users` (fullname → display_name, then email → email_address, ...): your `migrate`
starts at the window's start, and the new release rolls out 2 s later, one instance every
STEP seconds. Some windows bring trouble: the deploy is rolled back halfway (and then rolled
forward again), the replica falls behind, or the database gets busy with other work. The
first window is always at 0:20, with a rollback.

The run never restarts: the table, the fleet and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, rate_at, schedule
from core.services import ServiceError
from core.vtime import VirtualRun, now
from labs.zero_downtime_migration.lab import WINDOW

LAB = "zero_downtime_migration"
NAMES = ("read_name", "write_name", "migrate", "busy", "backfill", "verify",
         "BATCH", "PAUSE", "LOAD_MAX", "LAG_MAX", "GRACE")
PIECE = 60.0
DRAIN = 10.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a request still running after this long is a bug
SAMPLE = 0.25  # seconds between snapshots of the database and the fleet

INSTANCES = 6
WRITE_SHARE = 0.3
DEPLOY_DELAY = 2.0  # the rolling deploy starts this long after your migrate
STEP = 2.0  # seconds between two instances in a rolling deploy
RESTART = 1.0  # an instance is out of rotation this long while it restarts
BAKE = 4.0  # every instance new this long with no alarm: the release is final

READ_COST, WRITE_COST = 0.002, 0.004  # seconds a statement takes on an idle database
ROW_COST = 0.00075  # seconds per row a copy takes (it holds its rows' locks that long)
DIFF_COST = 0.00002  # seconds per row a diff takes (a read: no locks)
TRAFFIC_LOAD = 0.30  # the database's load from the app's own traffic
BF_LOAD = 0.60  # the extra load while copies run back to back
EMA = 1.0  # seconds: the load follows how much of about the last second the copies ran
SHUN_LOAD = 0.45  # extra load when the replica is out of the pool and its reads hit the primary
WARM, WARM_LOAD = 6.0, 0.10  # a restarted instance's caches are cold: this much extra load for WARM s
MAX_LOAD = 0.95
APPLY = 1500.0  # rows a second the replica applies
SHUN, BACK_IN = 2.0, 1.0  # seconds of lag: out of the pool above SHUN, back in below BACK_IN

# The columns each window renames (a code name never changes with the language).
RENAMES = (
    ("fullname", "display_name"), ("email", "email_address"), ("phone", "phone_number"),
    ("zip", "postal_code"), ("addr", "street_address"), ("nick", "username"),
    ("bday", "birth_date"), ("tz", "time_zone"), ("lang", "locale"), ("pic", "avatar_url"),
)
FIRST_RELEASE = 41  # the release every instance runs at 0:00

# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 20.0 + WINDOW, "rollback", 1.0, "canary_alarm")
KINDS = [
    Kind("deploy", 1.0, median=WINDOW, shortest=WINDOW, longest=WINDOW,
         causes=("weekly_release", "feature_launch", "hotfix")),
    Kind("rollback", 1.0, median=WINDOW, shortest=WINDOW, longest=WINDOW,
         causes=("canary_alarm", "error_spike", "bad_config")),
    Kind("lag", 1.0, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.10, 0.14),
         causes=("analytics_query", "replica_disk", "network_blip")),
    Kind("peak", 1.0, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.20, 0.28),
         causes=("traffic_peak", "nightly_job", "cache_flush")),
]
MEAN_GAP = 30.0
QUIET = 20.0  # at least this calm after a window

# Requests.
READ, WRITE = range(2)
OK, ERROR, WRONG = range(3)  # served; failed (a database error); a read that returned a wrong name
OLD_COL, NEW_COL = 1, 2  # bits: the columns a request touched
# Snapshot bits.
HAS_OLD, HAS_NEW, READS_NEW, WRITES_OLD = 1, 2, 4, 8
CALM, LAGGING, PEAK = range(3)  # trouble in a window


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def rename(k: int) -> tuple[str, str]:
    """The column window k renames: (old, new)."""
    old, new = RENAMES[k % len(RENAMES)]
    r = k // len(RENAMES)
    return (old, new) if r == 0 else (f"{old}{r + 1}", f"{new}{r + 1}")


class DbError(ServiceError):
    """The database refused a statement: a column that does not exist ("missing") or already does ("exists")."""

    def __init__(self, key: str, col: str) -> None:
        super().__init__(f"column users.{col} {'does not exist' if key == 'missing' else 'already exists'}")
        self.key, self.col = key, col


class Migration:
    """One rename, users.<old> → users.<new>, with the two flags every new instance reads."""

    table = "users"

    def __init__(self, sim: "_Sim", index: int) -> None:
        object.__setattr__(self, "_sim", sim)
        object.__setattr__(self, "index", index)
        old, new = rename(index)
        object.__setattr__(self, "old", old)
        object.__setattr__(self, "new", new)
        object.__setattr__(self, "read_new", False)  # read the new column (else the old one)
        object.__setattr__(self, "write_old", True)  # keep writing the old column too

    def __setattr__(self, name: str, value) -> None:
        before = getattr(self, name, None)
        object.__setattr__(self, name, value)
        if name in ("read_new", "write_old") and before != value:
            self._sim.step(f"{name}_{'on' if value else 'off'}", self.index)

    def __repr__(self) -> str:
        return f"Migration({self.table}.{self.old} → {self.new}, read_new={self.read_new}, write_old={self.write_old})"


_UNREAD = object()


class _Rec:
    """What one request did: its field, the name it writes, what a read should return, columns touched."""

    __slots__ = ("field", "name", "expect", "cols")

    def __init__(self, field: int, name: int | None) -> None:
        self.field, self.name, self.expect, self.cols = field, name, _UNREAD, 0


class Db:
    """The `users` table, as your code sees it. Statements take time; DDL is instant."""

    def __init__(self, sim: "_Sim", rec: _Rec | None = None) -> None:
        self._sim, self._rec = sim, rec

    @property
    def rows(self) -> int:
        """Rows in the table; ids are 0 .. rows - 1."""
        return self._sim.n

    def columns(self) -> set[str]:
        return set(self._sim.cols)

    def load(self) -> float:
        """The primary's load now, 0..1 (the app's traffic, your copies, everything else)."""
        return self._sim.load()

    def lag(self) -> float:
        """Seconds the replica is behind the primary."""
        return self._sim.lag()

    def _col(self, col: str) -> list:
        c = self._sim.cols.get(col)
        if c is None:
            raise DbError("missing", col)
        return c

    def _touch(self, col: str) -> None:
        if self._rec is not None:
            m = self._sim.migs[self._rec.field]
            self._rec.cols |= OLD_COL if col == m.old else NEW_COL if col == m.new else 0

    async def select(self, uid: int, col: str):
        """SELECT <col> FROM users WHERE id = uid. None is NULL."""
        s = self._sim
        await asyncio.sleep(s.latency(READ_COST))
        value = self._col(col)[uid]
        self._touch(col)
        if self._rec is not None:
            self._rec.expect = s.truth[self._rec.field][uid]
        return value

    async def update(self, uid: int, values: dict) -> None:
        """UPDATE users SET <col> = <value>, ... WHERE id = uid: every column at once, or none."""
        s = self._sim
        await asyncio.sleep(s.latency(WRITE_COST))
        while (lock := s.locked(uid)) is not None:  # a copy holds this row: wait for it to commit
            await lock.wait()
        cols = [self._col(c) for c in values]
        for c, (name, value) in zip(cols, values.items()):
            c[uid] = value
            self._touch(name)
        if self._rec is not None and self._rec.name is not None:
            s.truth[self._rec.field][uid] = self._rec.name
        s.replicate(1)
        s.recheck(uid, uid + 1)

    async def add_column(self, col: str) -> None:
        """ALTER TABLE users ADD COLUMN <col>: every row NULL. Instant (no default to write)."""
        s = self._sim
        if col in s.cols:
            raise DbError("exists", col)
        s.cols[col] = [None] * s.n
        s.ddl("add", col)

    async def rename_column(self, old: str, new: str) -> None:
        """ALTER TABLE users RENAME COLUMN <old> TO <new>. Instant."""
        s = self._sim
        self._col(old)
        if new in s.cols:
            raise DbError("exists", new)
        s.cols[new] = s.cols.pop(old)
        s.ddl("rename", f"{old} → {new}")

    async def drop_column(self, col: str) -> None:
        """ALTER TABLE users DROP COLUMN <col>. Instant."""
        s = self._sim
        self._col(col)
        del s.cols[col]
        s.ddl("drop", col)

    def _span(self, first: int, last: int | None) -> tuple[int, int]:
        n = self._sim.n
        return max(0, int(first)), n if last is None else min(n, int(last))

    async def copy(self, src: str, dst: str, first: int = 0, last: int | None = None) -> int:
        """UPDATE users SET <dst> = <src> WHERE first <= id < last (default: every row), in one
        statement: it takes ROW_COST a row, locks those rows until it commits, loads the
        database while it runs, and the replica must apply every row. Returns the rows copied."""
        s = self._sim
        a, b = self._span(first, last)
        self._col(src), self._col(dst)
        if b <= a:
            return 0
        lock = asyncio.Event()
        span = (a, b, lock)
        s.locks.append(span)
        s.running(+1)
        try:
            await asyncio.sleep((b - a) * ROW_COST)
            source, target = self._col(src), self._col(dst)
            target[a:b] = source[a:b]
            s.copied_rows(src, dst, a, b)
            s.replicate(b - a)
            s.recheck(a, b)
        finally:
            s.running(-1)
            s.locks.remove(span)
            lock.set()
        return b - a

    async def diff(self, col_a: str, col_b: str, first: int = 0, last: int | None = None) -> int:
        """SELECT count(*) FROM users WHERE first <= id < last AND <col_a> IS DISTINCT FROM <col_b>.
        A read: no locks, DIFF_COST a row."""
        s = self._sim
        a, b = self._span(first, last)
        self._col(col_a), self._col(col_b)
        if b <= a:
            return 0
        s.running(+1)
        try:
            await asyncio.sleep((b - a) * DIFF_COST)
        finally:
            s.running(-1)
        x, y = self._col(col_a), self._col(col_b)
        return sum(1 for i in range(a, b) if x[i] != y[i])


class Fleet:
    """The app instances, as your migration runner sees them."""

    def __init__(self, sim: "_Sim") -> None:
        self._sim = sim

    @property
    def old(self) -> int:
        """Instances on the old release (also while they restart)."""
        return sum(1 for i in self._sim.insts if i[0] == self._sim.base)

    @property
    def new(self) -> int:
        """Instances on the new release."""
        return len(self._sim.insts) - self.old

    async def all_new(self) -> None:
        """Wait until every instance runs the new release (the deploy may still be rolled back)."""
        while self.old:
            await asyncio.sleep(0.1)

    async def released(self) -> None:
        """Wait until the release is final: every instance new, and it can no longer be rolled back."""
        while not self._sim.released:
            await asyncio.sleep(0.1)


class OldRelease:
    """The release every instance runs before the deploy: it only knows the old column."""

    @staticmethod
    async def read_name(db: Db, m: Migration, uid: int):
        return await db.select(uid, m.old)

    @staticmethod
    async def write_name(db: Db, m: Migration, uid: int, name) -> None:
        await db.update(uid, {m.old: name})


class _Sim:
    def __init__(self, code, seed: int, rate: float, rows: int) -> None:
        self.code, self.seed, self.rate, self.n = code, seed, rate, int(rows)
        self.rng = random.Random(seed * 11 + 5)
        self.insts = [[FIRST_RELEASE, True] for _ in range(INSTANCES)]  # [release, up]
        self.base = FIRST_RELEASE  # the old release of the current window
        self.rr = 0
        self.cur = 0  # the field (rename) traffic uses now
        self.migs: dict[int, Migration] = {}
        self.truth: dict[int, list] = {}  # field -> every row's latest name
        self.cols: dict[str, list] = {}
        self.locks: list[tuple[int, int, asyncio.Event]] = []
        self.released = True
        self.peak = 0.0
        self.warm = [0.0] * INSTANCES  # until when each instance warms up after a restart
        self.apply = APPLY
        self.trouble = CALM
        self.backlog, self.lag_t, self.shunned = 0.0, 0.0, False
        self.bf_running, self.ema, self.ema_t = 0, 0.0, 0.0
        self.copied = bytearray(0)
        self.copied_n = 0
        self.wrong: set[int] = set()  # rows whose new column holds a name that is not the latest
        self.requests: list[tuple] = []  # (id, start, end, kind, outcome, instance, new release, columns)
        self.samples: list[tuple] = []
        self.steps: list[tuple] = []  # (t, key, window, detail)
        self.windows: list[tuple] = []  # (t1, window, t0, done at or None, wrong rows at the end, old, new)
        self.holding: dict[int, float] = {}
        self.planned: list[Planned] = []
        self.runner: asyncio.Task | None = None
        self.done_at: float | None = None
        self.bugs: list[BaseException] = []
        self.field(0)

    # ---------------------------------------------------------------- the table

    def field(self, k: int) -> None:
        """Make rename k the one traffic uses: its old column, full of names."""
        m = self.migs[k] = Migration(self, k)
        self.truth[k] = [k * 1_000_000 + i for i in range(self.n)]
        self.cols[m.old] = list(self.truth[k])
        self.cur = k
        self.copied = bytearray(self.n)
        self.copied_n = 0
        self.wrong = set()

    def ddl(self, key: str, detail: str) -> None:
        self.step(key, self.cur, detail)
        self.recheck(0, self.n)

    def recheck(self, a: int, b: int) -> None:
        """Which rows of [a, b) hold a stale name in the current field's new column."""
        m = self.migs[self.cur]
        col = self.cols.get(m.new)
        truth = self.truth[self.cur]
        wrong = self.wrong
        if col is None:
            if a == 0 and b == self.n:
                wrong.clear()
            return
        for i in range(a, b):
            v = col[i]
            if v is not None and v != truth[i]:
                wrong.add(i)
            else:
                wrong.discard(i)

    def copied_rows(self, src: str, dst: str, a: int, b: int) -> None:
        m = self.migs[self.cur]
        if (src, dst) == (m.old, m.new):
            self.copied_n += (b - a) - sum(self.copied[a:b])
            self.copied[a:b] = b"\x01" * (b - a)
            if self.copied_n == self.n and not any(s[1] == "copied" and s[2] == self.cur for s in self.steps):
                self.step("copied", self.cur)

    def locked(self, uid: int) -> asyncio.Event | None:
        for a, b, ev in self.locks:
            if a <= uid < b:
                return ev
        return None

    # ---------------------------------------------------------------- load and the replica

    def running(self, delta: int) -> None:
        self.duty()
        self.bf_running += delta

    def duty(self) -> float:
        """How much of about the last second copies ran (an exponential average)."""
        t = now()
        dt = t - self.ema_t
        if dt > 0:
            on = 1.0 if self.bf_running else 0.0
            self.ema = on + (self.ema - on) * math.exp(-dt / EMA)
            self.ema_t = t
        return self.ema

    def lag(self) -> float:
        t = now()
        dt = t - self.lag_t
        if dt > 0:
            self.backlog = max(0.0, self.backlog - self.apply * dt)
            self.lag_t = t
        lag = self.backlog / self.apply
        if lag > SHUN and not self.shunned:
            self.shunned = True
            self.step("shunned", self.cur)
        elif lag < BACK_IN and self.shunned:
            self.shunned = False
            self.step("back_in", self.cur)
        return lag

    def replicate(self, rows: int) -> None:
        self.lag()
        self.backlog += rows

    def parts(self) -> tuple[float, float, float]:
        """The load now: (the app's traffic, other work, your copies)."""
        self.lag()
        traffic = TRAFFIC_LOAD * rate_at(1.0, now(), self.seed)
        t = now()
        other = self.peak + (SHUN_LOAD if self.shunned else 0.0) + WARM_LOAD * sum(1 for w in self.warm if w > t)
        return traffic, other, BF_LOAD * self.duty()

    def load(self) -> float:
        return min(MAX_LOAD, sum(self.parts()))

    def latency(self, base: float) -> float:
        return base / (1.0 - self.load()) * (0.5 + self.rng.expovariate(2.0))

    # ---------------------------------------------------------------- events

    def step(self, key: str, window: int, detail="") -> None:
        self.steps.append((now(), key, window, detail))

    def sample(self) -> None:
        traffic, other, bf = self.parts()
        m = self.migs[self.cur]
        bits = ((HAS_OLD if m.old in self.cols else 0) | (HAS_NEW if m.new in self.cols else 0)
                | (READS_NEW if m.read_new else 0) | (WRITES_OLD if m.write_old else 0))
        old = sum(1 for i in self.insts if i[0] == self.base)
        down = sum(1 for i in self.insts if not i[1])
        self.samples.append((now(), self.cur, traffic, other, bf, self.lag(), self.shunned, old,
                             INSTANCES - old, down, bits, self.copied_n, len(self.wrong),
                             self.bf_running > 0, self.trouble, self.base))

    # ---------------------------------------------------------------- the users

    def pick(self) -> int:
        ups = [k for k, i in enumerate(self.insts) if i[1]]
        self.rr += 1
        return ups[self.rr % len(ups)]

    async def request(self, rid: int, uid: int, write: bool) -> None:
        start = now()
        self.holding[rid] = start
        k = self.pick()
        field = self.cur
        m = self.migs[field]
        new = self.insts[k][0] > self.base
        code = self.code if new else OldRelease
        rec = _Rec(field, 1_000_000_000 + rid if write else None)
        db = Db(self, rec)
        outcome = OK
        try:
            if write:
                await code.write_name(db, m, uid, rec.name)
            else:
                value = await code.read_name(db, m, uid)
                expect = self.truth[field][uid] if rec.expect is _UNREAD else rec.expect
                if value != expect:
                    outcome = WRONG
        except DbError:
            outcome = ERROR
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            outcome = ERROR
        finally:
            del self.holding[rid]
        self.requests.append((rid, start, now(), WRITE if write else READ, outcome, k, new, rec.cols))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        pick = random.Random(self.seed * 13 + 1)
        for rid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.request(rid, pick.randrange(self.n), pick.random() < WRITE_SHARE))

    async def sampler(self) -> None:
        while True:
            self.sample()
            await asyncio.sleep(SAMPLE)

    # ---------------------------------------------------------------- the windows

    async def roll(self, which, release: int) -> None:
        """A rolling deploy: one instance after another restarts on `release`."""
        for j, k in enumerate(which):
            if j:
                await asyncio.sleep(STEP - RESTART)
            self.insts[k][1] = False
            await asyncio.sleep(RESTART)
            self.insts[k][0], self.insts[k][1] = release, True
            self.warm[k] = now() + WARM

    async def deploy(self, k: int, inc: Planned, rng: random.Random) -> None:
        new = self.base + 1
        await asyncio.sleep(inc.t0 + DEPLOY_DELAY - now())
        self.step("deploy", k, new)
        await self.roll(range(INSTANCES), new)
        if inc.kind == "rollback":
            await asyncio.sleep(rng.uniform(1.5, 3.5))  # the alarm fires while the release bakes
            self.step("rollback", k, inc.cause)
            half = list(range(INSTANCES // 2, INSTANCES))
            await self.roll(reversed(half), self.base)
            await asyncio.sleep(rng.uniform(3.0, 6.0))  # found: not this release's fault
            self.step("forward", k, new)
            await self.roll(half, new)
        await asyncio.sleep(BAKE)
        self.released = True
        self.step("released", k, new)

    async def trouble_in(self, k: int, inc: Planned, rng: random.Random) -> None:
        """A lagging replica or a busy database, for a while in the middle of the window."""
        if inc.kind not in ("lag", "peak"):
            return
        await asyncio.sleep(inc.t0 + rng.uniform(13.0, 18.0) - now())
        self.lag()
        if inc.kind == "lag":
            self.apply, self.trouble = APPLY * inc.severity, LAGGING
        else:
            self.peak, self.trouble = inc.severity, PEAK
        self.step(f"{inc.kind}_start", k, inc.cause)
        await asyncio.sleep(rng.uniform(10.0, 18.0))
        self.lag()
        self.apply, self.peak, self.trouble = APPLY, 0.0, CALM
        self.step(f"{inc.kind}_end", k)

    async def migrate(self, k: int) -> None:
        """Your migration runner, for window k."""
        m = self.migs[k]
        try:
            await self.code.migrate(Db(self), m, Fleet(self))
        except DbError as exc:
            self.step("failed", k, (exc.key, exc.col))
            return
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        if m.old not in self.cols and m.new in self.cols:
            self.done_at = now()
            self.step("done", k)
        else:
            self.step("unfinished", k)

    async def chaos(self) -> None:
        for k, inc in enumerate(incidents(self.seed)):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            rng = random.Random(self.seed * 1_000 + k)
            self.released, self.done_at = False, None
            self.runner = asyncio.ensure_future(self.migrate(k))
            deploy = asyncio.ensure_future(self.deploy(k, inc, rng))
            trouble = asyncio.ensure_future(self.trouble_in(k, inc, rng))
            await asyncio.sleep(inc.t1 - now())
            if not self.runner.done():
                self.runner.cancel()
                self.step("cut", k)
            for task in (deploy, trouble):
                task.cancel()
            m = self.migs[k]
            final = m.new if m.new in self.cols else m.old
            col, truth = self.cols.get(final), self.truth[k]
            wrong = self.n if col is None else sum(1 for a, b in zip(col, truth) if a != b)
            self.windows.append((inc.t1, k, inc.t0, self.done_at, wrong, m.old, m.new))
            # The window is over: every instance runs the new release, the next one about another column.
            self.base += 1
            for i in self.insts:
                i[0], i[1] = self.base, True
            self.released = True
            self.field(k + 1)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 100.0, rows: int = 10_000) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate, rows)
    sim.spawn(s.traffic())
    sim.spawn(s.sampler())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.holding.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "samples": s.take(s.samples, 0, a, b),
                    "steps": s.take(s.steps, 0, a, b),
                    "windows": s.take(s.windows, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
