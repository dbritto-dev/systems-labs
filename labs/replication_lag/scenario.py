"""Lab replication_lag: one endless run on virtual time, handed out a minute at a time.

A primary and 4 asynchronous read replicas (r1..r4). Every write commits on the primary
and reaches each replica 50-200 ms later. ~200 sessions (users) write their profile and
some popular pages, and read them back; your `Router` picks where every read goes.

Incidents come at random, like in production: one replica falls seconds behind (a long
analytics query, autovacuum, a network brownout), a replica restarts and catches up, or a
write spike puts every replica behind. The first one is always replica r2 falling 6 s
behind at 0:20-0:30.

The checker knows the truth: for every read it records whether the session missed its own
write (read-your-writes) or saw an older version than it had already seen (monotonic reads).
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_right
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.replication_lag import lab

LAB = "replication_lag"
NAMES = ("Router",)
PIECE = 60.0
DRAIN = 5.0
STUCK = 30.0
SESSIONS = 200
HOT = 20  # popular pages everybody reads, written now and then
WRITE_SHARE = 0.15  # of operations
READ_BACK = 0.5  # after writing their profile, half the users look at it right away
HEARTBEAT = 0.1  # replicas report how far they are this often
LAG_EVERY = 0.1
NAMES_OF = ["primary"] + [f"r{i}" for i in range(1, lab.REPLICAS + 1)]
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "behind", 6.0, "analytics_query")
KINDS = [
    Kind("behind", 0.5, median=10.0, shortest=5.0, longest=25.0, severity=(2.0, 10.0),
         causes=("analytics_query", "autovacuum", "brownout")),
    Kind("restart", 0.25, median=8.0, shortest=4.0, longest=15.0, causes=("kernel_patch", "oom_kill")),
    Kind("spike", 0.25, median=10.0, shortest=5.0, longest=20.0, severity=(0.5, 1.5),
         causes=("bulk_import", "marketing_email")),
]
MEAN_GAP = 30.0
QUIET = 25.0


@dataclass(frozen=True, slots=True)
class Replica:
    """What the router knows about a replica: its name, the log position (LSN) it has
    applied as of its last report (every 100 ms), and whether it answers at all."""

    name: str
    lsn: int
    up: bool


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def target(inc) -> int:
    """The replica (1..4) an incident hits (a write spike hits them all). The first one is always r2."""
    if inc.t0 == FIRST.t0:
        return 2
    return random.Random(int(inc.t0 * 1000)).randrange(1, lab.REPLICAS + 1)


class _Replica:
    def __init__(self) -> None:
        self.queue: deque[tuple[float, int]] = deque()  # (applied at, lsn), in order
        self.applied = 0
        self.last_apply = 0.0
        self.down_from = -1.0
        self.down_until = -1.0  # restarting: it answers nothing until then

    def lsn_at(self, t: float) -> int:
        while self.queue and self.queue[0][0] <= t:
            self.applied = self.queue.popleft()[1]
        return self.applied


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.rng = random.Random(seed * 13 + 5)
        self.router = code.Router(rng=random.Random(seed * 13 + 6))
        self.replicas = [_Replica() for _ in range(lab.REPLICAS)]
        self.lsn = 0
        self.committed: dict[int, float] = {}  # lsn -> when it committed (trimmed)
        self.history: dict[str, list[int]] = {}  # key -> the lsns that wrote it
        self.last_write: dict[int, int] = {}  # session -> lsn of its last profile write
        self.seen: dict[tuple[int, str], int] = {}  # (session, key) -> newest version it saw
        self.snapshot = [Replica(NAMES_OF[i + 1], 0, True) for i in range(lab.REPLICAS)]
        self.active: tuple[Planned, int] | None = None
        self.planned: list[Planned] = []
        self.reads: list[tuple] = []
        self.writes: list[tuple] = []
        self.lag: list[tuple] = []
        self.open: dict[int, float] = {}
        self.bugs: list[BaseException] = []
        self._ids = itertools.count()

    # ---- the replicas

    def delay(self, r: int) -> float:
        d = self.rng.uniform(0.05, 0.2)
        if self.active is not None:
            inc, hit = self.active
            if inc.kind == "behind" and hit == r + 1:
                d += inc.severity
            elif inc.kind == "spike":
                d += inc.severity
        return d

    def write(self, session: int, key: str) -> int:
        t = now()
        self.lsn += 1
        lsn = self.lsn
        self.committed[lsn] = t
        self.history.setdefault(key, []).append(lsn)
        delays = []
        for r, rep in enumerate(self.replicas):
            at = max(rep.last_apply + 0.0005, t + self.delay(r))
            if rep.down_until > t:  # restarting: it replays what it missed after it is back
                at = max(at, rep.down_until + 0.25 * (t - rep.down_from))
            rep.last_apply = at
            rep.queue.append((at, lsn))
            delays.append(round(at - t, 4))
        self.writes.append((t, session, key == f"u{session}", lsn, *delays))
        return lsn

    def version(self, key: str, lsn: int) -> int:
        h = self.history.get(key, [])
        i = bisect_right(h, lsn)
        return h[i - 1] if i else 0

    # ---- users

    async def op_write(self, session: int, own: bool) -> None:
        key = f"u{session}" if own else f"p{self.rng.randrange(HOT)}"
        await asyncio.sleep(self.rng.uniform(0.002, 0.004))
        lsn = self.write(session, key)
        if own:
            self.last_write[session] = lsn
        self.router.wrote(session, lsn)
        if own and self.rng.random() < READ_BACK:  # look at it right away
            await asyncio.sleep(self.rng.uniform(0.02, 0.06))
            await self.op_read(session, key)

    async def op_read(self, session: int, key: str) -> None:
        k = next(self._ids)
        start = now()
        self.open[k] = start
        must_see = self.last_write.get(session, 0)  # writes after the read started do not count
        try:
            name = self.router.pick(session, key, list(self.snapshot))
            if name not in NAMES_OF:
                raise ValueError(lab_text(LAB).STRINGS["bad_pick"].format(name=name, last=lab.REPLICAS))
            node = NAMES_OF.index(name)
            await asyncio.sleep(self.rng.uniform(0.002, 0.006))
            t = now()
            if node == 0:
                applied, ok = self.lsn, True
            else:
                rep = self.replicas[node - 1]
                ok = rep.down_until <= t
                applied = rep.lsn_at(t)
            if not ok:
                self.reads.append((start, session, node, now(), False, False, False, 0))
                return
            v = self.version(key, applied)
            own = key == f"u{session}"
            ryw = own and must_see > v
            mono = v < self.seen.get((session, key), 0)
            self.seen[(session, key)] = max(v, self.seen.get((session, key), 0))
            self.router.saw(session, key, name, v)
            self.reads.append((start, session, node, now(), True, ryw, mono, self.lsn - applied))
        except Exception as exc:  # a bug in the router: surface it
            self.bugs.append(exc)
        finally:
            self.open.pop(k, None)

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 13 + 7)
        for t in arrivals(self.rate, self.seed, 0.2, rng):
            await asyncio.sleep(t - now())
            session = rng.randrange(SESSIONS)
            if rng.random() < WRITE_SHARE:
                asyncio.ensure_future(self.op_write(session, own=rng.random() < 0.5))
            else:
                key = f"u{session}" if rng.random() < 0.3 else f"p{min(HOT - 1, int(rng.paretovariate(1.2)) - 1)}"
                asyncio.ensure_future(self.op_read(session, key))

    async def heartbeat(self) -> None:
        while True:
            t = now()
            self.snapshot = [Replica(NAMES_OF[i + 1], rep.lsn_at(t), rep.down_until <= t)
                             for i, rep in enumerate(self.replicas)]
            await asyncio.sleep(HEARTBEAT)

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            hit = target(inc)
            self.active = (inc, hit)
            if inc.kind == "restart":
                self.replicas[hit - 1].down_from, self.replicas[hit - 1].down_until = inc.t0, inc.t1
            await asyncio.sleep(inc.t1 - now())
            self.active = None

    async def sampler(self) -> None:
        """Every 100 ms: how far behind each replica is (seconds since its oldest missing write)."""
        while True:
            t = now()
            lags, ups = [], []
            for rep in self.replicas:
                rep.lsn_at(t)
                pending = rep.queue[0][1] if rep.queue else None
                lags.append(round(t - self.committed.get(pending, t), 3) if pending is not None else 0.0)
                ups.append(rep.down_until <= t)
            self.lag.append((t, tuple(lags), tuple(ups)))
            oldest = min(rep.applied for rep in self.replicas)
            for lsn in [x for x in self.committed if x <= oldest - 1000]:
                del self.committed[lsn]
            await asyncio.sleep(LAG_EVERY)


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 200.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for coro in (s.traffic(), s.heartbeat(), s.chaos(), s.sampler()):
        sim.spawn(coro)
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
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    # (start, session, node 0=primary 1..4, end, answered, missed own write, went back, lsn gap)
                    "reads": _take(s.reads, 0, a, b),
                    # (time, session, own profile?, lsn, delay to r1, r2, r3, r4)
                    "writes": _take(s.writes, 0, a, b),
                    # (time, seconds behind per replica, up per replica)
                    "lag": _take(s.lag, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
