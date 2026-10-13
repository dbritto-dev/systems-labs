"""Lab conn_pool: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (Poisson, drifting slowly like real traffic). Each request
gets a database connection from your `Pool`, runs one query, and gives the connection
back. Opening a connection is expensive (~40 ms: TLS, auth, a new backend process); a
query is cheap (~8 ms). The database allows at most 50 open connections ("too many
connections" beyond) and slows down when more than ~20 are working at once.

Incidents come at random, like in production: the database slows down (a vacuum, a long
report, a missing index) or traffic spikes (a marketing email, a cron job fanning out).
The first incident is always a slowdown at 0:20-0:32. The run never restarts: the pool,
its connections and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import current_request
from core.vtime import VirtualRun, now

LAB = "conn_pool"
NAMES = ("Pool", "PoolTimeout")
PIECE = 60.0
DRAIN = 40.0  # simulate this far past a minute before handing it out (long waits finish)
STUCK = 60.0  # a request still running after this long is a bug
SAMPLE = 0.1  # how often the database's connection counts are recorded

MAX_CONNECTIONS = 50
CORES = 20  # past this many connections working at once, everything slows down
CONNECT_TIME = 0.040
QUERY_TIME = 0.008

FIRST = Planned(20.0, 32.0, "slowdown", 45.0, "autovacuum is rewriting the orders table")
KINDS = [
    Kind("slowdown", 0.55, median=10.0, shortest=8.0, longest=14.0, severity=(35.0, 55.0), causes=(
        "autovacuum is rewriting the orders table",
        "a long report holds locks on the orders table",
        "a backup saturates the disks",
        "a deploy dropped an index, queries scan the table",
    )),
    Kind("spike", 0.45, median=11.0, shortest=8.0, longest=15.0, severity=(5.0, 7.0), causes=(
        "a marketing email went out",
        "a cron job fans out to every user",
        "a mobile release made every app refresh at once",
    )),
]
MEAN_GAP = 30.0
QUIET = 22.0  # at least this calm after an incident: a 15 s baseline + time to judge it

# Why a request failed.
OK, TOO_MANY, TIMED_OUT = 0, 1, 2


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class TooManyConnections(Exception):
    """The database refused a new connection: it already has `max_connections` open."""


class Connection:
    """One open database connection. `await conn.query()` runs one query on it."""

    def __init__(self, db: "Database") -> None:
        self.db = db
        self.closed = False

    async def query(self) -> None:
        if self.closed:
            raise RuntimeError("query on a closed connection")
        await self.db._work(QUERY_TIME * self.db.slow)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.db.open -= 1


class Database:
    """A database with a connection limit and a fixed number of cores.

    `await db.connect()` opens a connection (slow) or raises TooManyConnections.
    Work (connecting, querying) slows down once more than `CORES` things run at once.
    """

    def __init__(self, rng: random.Random) -> None:
        self.max_connections = MAX_CONNECTIONS
        self.open = 0
        self.active = 0
        self.slow = 1.0
        self.rng = rng
        self.connected: set[int | None] = set()  # requests that opened a connection

    async def _work(self, seconds: float) -> None:
        self.active += 1
        try:
            contention = max(1.0, self.active / CORES)
            await asyncio.sleep(seconds * contention * self.rng.uniform(0.8, 1.2))
        finally:
            self.active -= 1

    async def connect(self) -> Connection:
        if self.open >= self.max_connections:
            await asyncio.sleep(0.002)
            raise TooManyConnections(f"too many connections ({self.max_connections} open)")
        self.open += 1
        self.connected.add(current_request.get())
        try:
            await self._work(CONNECT_TIME)
        except BaseException:
            self.open -= 1
            raise
        return Connection(self)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.db = Database(random.Random(seed * 7 + 1))
        self.pool = code.Pool(self.db)
        self.ids = itertools.count()
        self.requests: list[tuple] = []  # (id, start, end, ok, wait, new connection, failure)
        self.samples: list[tuple] = []  # (t, open, working)
        self.open: dict[int, float] = {}
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    async def request(self, rid: int) -> None:
        current_request.set(rid)
        start = now()
        self.open[rid] = start
        wait, ok, failure = None, False, OK
        try:
            try:
                conn = await self.pool.acquire()
            except TooManyConnections:
                failure = TOO_MANY
            except (self.code.PoolTimeout, TimeoutError):
                failure = TIMED_OUT
            else:
                wait = now() - start
                try:
                    await conn.query()
                finally:
                    self.pool.release(conn)
                ok = True
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            return
        finally:
            self.open.pop(rid, None)
        if wait is None:
            wait = now() - start
        new = rid in self.db.connected
        self.db.connected.discard(rid)
        self.requests.append((rid, start, now(), ok, wait, new, failure))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.request(next(self.ids)))

    async def burst(self, until: float, extra: float, rng: random.Random) -> None:
        t = now()
        while True:
            t += rng.expovariate(extra)
            if t >= until:
                return
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.request(next(self.ids)))

    async def chaos(self) -> None:
        rng = random.Random(self.seed * 7 + 2)
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "slowdown":
                self.db.slow = inc.severity
                await asyncio.sleep(inc.t1 - now())
                self.db.slow = 1.0
            else:
                await self.burst(inc.t1, self.rate * (inc.severity - 1), rng)

    async def sampler(self) -> None:
        while True:
            self.samples.append((round(now(), 3), self.db.open, self.db.active))
            await asyncio.sleep(SAMPLE)

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
    for task in (s.traffic(), s.chaos(), s.sampler()):
        sim.spawn(task)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.open.values()):
                raise RuntimeError(f"a request has waited for a connection for over {STUCK:.0f} s: "
                                   "does release() wake up the requests waiting in acquire()?")
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "samples": s.take(s.samples, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 100.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
