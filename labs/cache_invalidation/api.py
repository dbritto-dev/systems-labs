"""What your ProductCache gets: a shared cache (like memcached) and the product database.

    record = await db.read(key)                  SELECT price, stock FROM products WHERE id = key
    await db.write(key, record)                  UPDATE products SET ... WHERE id = key; COMMIT
                                                 raises WriteFailed when the database refuses it (a
                                                 lock wait timeout, a constraint): nothing was written

    record = await cache.get(key)                the cached record, or None (a miss)
    await cache.set(key, record, ttl)            store it for `ttl` seconds, whatever is there
    await cache.delete(key)                      forget it

    lease = await cache.lease_get(key)           a hit: lease.value is the record, lease.token None
                                                 a miss: lease.value None, lease.token a number: the
                                                 right to fill this key, until somebody deletes it
    ok = await cache.lease_set(key, record, lease.token, ttl)
                                                 stores it only if the token is still valid (no delete
                                                 or set of this key since it was issued); False if not

Every call is a round trip over the network: ~0.6 ms to the cache, ~4 ms to read the database and
~6 ms to commit a write (much more when the network is slow). The app servers also stop now and then
(a garbage-collection pause, 30-150 ms): whatever a request was doing, it resumes late. So between a
request's `db.read` and its `cache.set`, another app server can write the database and delete the key.

While the cache node restarts it answers nothing: `get` and `lease_get` miss (no token), `set`,
`lease_set` and `delete` do nothing. It comes back empty.
"""

from __future__ import annotations

import asyncio
import random
from bisect import bisect_right
from collections.abc import Callable
from contextvars import ContextVar
from typing import NamedTuple

from core.vtime import now

CACHE_LATENCY = 0.0006  # a round trip to the cache
READ_LATENCY = 0.004  # a round trip to read a product from the database
WRITE_LATENCY = 0.006  # a round trip to write one and commit
QUERY = (0.008, 0.025)  # seconds the product query runs, after it took its snapshot

# The request being served: the scenario sets it, the cache and the database note what it did.
current_request: ContextVar[dict | None] = ContextVar("current_request", default=None)

# What a fill did to the cache (the scenario keeps these for the pictures).
FILLED, FILLED_STALE, REFUSED = range(3)


class Record(NamedTuple):
    """One product, as the database has it. `write` says which write made it (the lab uses it to
    tell a fresh record from a stale one); your code just passes records along."""

    price: int  # cents
    stock: int
    write: int


class Lease(NamedTuple):
    value: Record | None  # the record on a hit
    token: int | None  # on a miss: the right to fill the key (None while the cache is restarting)


class WriteFailed(Exception):
    """The database refused the write (a lock wait timeout, a constraint): nothing was written."""


def _trip(rng: random.Random, latency: float, slow: float = 1.0) -> float:
    """Half a round trip: jittered, with a rare long tail (a retransmitted packet), `slow` times
    longer and more often on a slow network."""
    half = latency * slow / 2 * (0.8 + 0.4 * rng.random())
    return half * rng.uniform(4, 12) if rng.random() < 0.01 * slow else half


class Database:
    """Products by key. A read or a write runs half way through its round trip, in one step.

    It also keeps, for the lab, the order in which writes committed for each key (`index`), when,
    and which writes failed, so a record can be told fresh or stale.
    """

    def __init__(self, keys: int, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.slow = 1.0  # every round trip takes this many times longer (a slow network)
        self.fail = 0.0  # the share of writes the database refuses
        self.rows: dict[int, Record] = {k: Record(1000 + 37 * k % 9000, 50, -1 - k) for k in range(keys)}
        self.index: dict[int, int] = {}  # write id -> its place in its key's order (0 = the first record)
        self.commits: dict[int, list[float]] = {k: [float("-inf")] for k in range(keys)}  # key -> commit times
        for k, r in self.rows.items():
            self.index[r.write] = 0
        self.failed: dict[int, float] = {}  # write id -> when the database refused it
        self.reads = 0  # reads so far (the scenario samples it every second)

    async def read(self, key: int) -> Record:
        await asyncio.sleep(_trip(self.rng, READ_LATENCY, self.slow))
        self.reads += 1
        record = self.rows[key]  # the query's snapshot: what it returns is the row as of now
        req = current_request.get()
        if req is not None:
            req["db"] += 1
        await asyncio.sleep(self.rng.uniform(*QUERY))  # joins prices, stock and promotions
        await asyncio.sleep(_trip(self.rng, READ_LATENCY, self.slow))
        return record

    async def write(self, key: int, record: Record) -> None:
        await asyncio.sleep(_trip(self.rng, WRITE_LATENCY, self.slow))
        if self.rng.random() < self.fail:
            self.failed[record.write] = now()
            await asyncio.sleep(_trip(self.rng, WRITE_LATENCY, self.slow))
            raise WriteFailed(key)
        if record.write not in self.index:  # the same record written twice counts once
            self.rows[key] = record
            self.index[record.write] = len(self.commits[key])
            self.commits[key].append(now())
        await asyncio.sleep(_trip(self.rng, WRITE_LATENCY, self.slow))

    # ---- for the lab: is a record stale?

    def latest(self, key: int, t: float) -> int:
        """The index of the newest record of `key` committed at or before t."""
        return bisect_right(self.commits[key], t) - 1

    def phantom(self, record: Record) -> bool:
        """A record the database never committed (its write failed)."""
        return record.write in self.failed


class Cache:
    """One shared cache node: records by key with an expiry time, and lease tokens.

    `set` and `delete` invalidate every lease token issued for the key; `lease_set` with a token
    that is no longer valid is refused. `on_fill(key, record, result)` is told about every fill a
    read request makes (the scenario draws them).
    """

    def __init__(self, rng: random.Random | None = None,
                 on_fill: Callable[[int, Record, int], None] | None = None,
                 db: Database | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.slow = 1.0
        self.up = True
        self.data: dict[int, tuple[Record, float]] = {}  # key -> (record, expires at)
        self.leases: dict[int, set[int]] = {}  # key -> valid tokens
        self.tokens = 0
        self.on_fill = on_fill
        self.db = db  # only to tell the pictures whether a fill was stale

    async def _go(self) -> None:
        await asyncio.sleep(_trip(self.rng, CACHE_LATENCY, self.slow))

    async def get(self, key: int) -> Record | None:
        await self._go()
        found = self._lookup(key)
        await self._go()
        return found

    async def set(self, key: int, record: Record, ttl: float) -> None:
        await self._go()
        if self.up:
            self.leases.pop(key, None)
            self._store(key, record, ttl)
            self._filled(key, record, FILLED)
        await self._go()

    async def delete(self, key: int) -> None:
        await self._go()
        if self.up:
            self.data.pop(key, None)
            self.leases.pop(key, None)
        await self._go()

    async def lease_get(self, key: int) -> Lease:
        await self._go()
        found = self._lookup(key)
        token = None
        if found is None and self.up:
            self.tokens += 1
            token = self.tokens
            self.leases.setdefault(key, set()).add(token)
        await self._go()
        return Lease(found, token)

    async def lease_set(self, key: int, record: Record, token: int | None, ttl: float) -> bool:
        await self._go()
        valid = self.up and token is not None and token in self.leases.get(key, ())
        if valid:
            self.leases[key].discard(token)
            self._store(key, record, ttl)
            self._filled(key, record, FILLED)
        elif self.up:
            self._filled(key, record, REFUSED)
        await self._go()
        return valid

    # ---- inside the node

    def _lookup(self, key: int) -> Record | None:
        if not self.up:
            return None
        hit = self.data.get(key)
        if hit is None:
            return None
        if hit[1] <= now():
            del self.data[key]
            return None
        return hit[0]

    def _store(self, key: int, record: Record, ttl: float) -> None:
        self.data[key] = (record, now() + max(0.0, float(ttl)))

    def _filled(self, key: int, record: Record, result: int) -> None:
        req = current_request.get()
        if self.on_fill is None or req is None or req.get("write"):
            return  # only fills by read requests are drawn
        if result == FILLED and self.db is not None:
            if self.db.phantom(record) or self.db.index.get(record.write, 1 << 30) < self.db.latest(key, now()):
                result = FILLED_STALE  # older than what the database has now
        self.on_fill(key, record, result)

    def restart(self) -> None:
        """The node goes down: it forgets everything, tokens included."""
        self.up = False
        self.data.clear()
        self.leases.clear()

    def back(self) -> None:
        self.up = True

    def stale(self, db: Database, t: float, grace: float) -> tuple[int, int]:
        """(entries older than the database's record from at least `grace` ago, entries) at t."""
        bad = n = 0
        for key, (record, expires) in self.data.items():
            if expires <= t:
                continue
            n += 1
            failed = db.failed.get(record.write)
            if failed is not None:
                bad += failed <= t - grace
            elif record.write in db.index and db.index[record.write] < db.latest(key, t - grace):
                bad += 1
        return bad, n


class Server:
    """One app server: it stops now and then (a garbage-collection pause)."""

    def __init__(self) -> None:
        self.paused_until = float("-inf")

    async def resume(self) -> None:
        """A request whose reply arrives during a pause carries on only when the pause ends."""
        wait = self.paused_until - now()
        if wait > 0:
            await asyncio.sleep(wait)


class CacheClient:
    """The cache, as one app server sees it (its pauses included). Same calls as Cache."""

    def __init__(self, cache: Cache, server: Server) -> None:
        self._cache, self._server = cache, server

    async def get(self, key):
        r = await self._cache.get(key)
        await self._server.resume()
        return r

    async def set(self, key, record, ttl):
        await self._cache.set(key, record, ttl)
        await self._server.resume()

    async def delete(self, key):
        await self._cache.delete(key)
        await self._server.resume()

    async def lease_get(self, key):
        r = await self._cache.lease_get(key)
        await self._server.resume()
        return r

    async def lease_set(self, key, record, token, ttl):
        r = await self._cache.lease_set(key, record, token, ttl)
        await self._server.resume()
        return r


class DatabaseClient:
    """The database, as one app server sees it. Same calls as Database."""

    def __init__(self, db: Database, server: Server) -> None:
        self._db, self._server = db, server

    async def read(self, key):
        r = await self._db.read(key)
        await self._server.resume()
        return r

    async def write(self, key, record):
        try:
            await self._db.write(key, record)
        finally:
            await self._server.resume()
