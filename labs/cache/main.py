"""Lab cache: YOUR FILE. Edit it and save; the live window reruns it.

Users open ~200 pages/s; each page reads 3 keys through `get()`. A few keys
are very hot. The database takes 20 ms per read and does 8 at a time (about
400 reads/s); beyond that reads wait in a queue. Right now `get()` sends
every read to the database, so the queue never empties.

Do the stages in order, in this file:

  Stage 1  Cache-aside with a TTL: `Cache.lookup`, `Cache.store`, and use
           them in `get()`.
  Stage 2  Stampede protection: single-flight loads in `get()` (concurrent
           misses for one key share one database read), and jittered TTLs
           in `Cache.store` (keys loaded together do not expire together).

Check yourself:  uv run pytest labs/cache
Peek at a solution (after trying!):  labs/cache/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.vtime import now


class Cache:
    """An in-memory cache. The scenario makes one and calls `clear()` on a flush.

    Contract:
      - `lookup(key)` returns the value, or None on a miss or if it expired.
      - `store(key, value)` keeps it for `ttl` seconds (`now()` is the clock).
      - `clear()` forgets everything (a deploy or a restart).
    """

    def __init__(self, ttl: float = 30.0, rng: random.Random | None = None) -> None:
        self.ttl = ttl
        self.rng = rng or random.Random(0)
        self.data: dict = {}  # key -> (value, expires at)
        self.loading: dict = {}  # Stage 2: key -> future of the load in flight

    def clear(self) -> None:
        self.data.clear()

    def lookup(self, key):
        # Stage 1: return the value if it is there and now() < its expiry time.
        raise NotImplementedError("TODO stage 1: Cache.lookup")

    def store(self, key, value) -> None:
        # Stage 1: self.data[key] = (value, now() + self.ttl)
        # Stage 2: jitter the TTL, e.g. self.ttl * self.rng.uniform(0.8, 1.2)
        raise NotImplementedError("TODO stage 1: Cache.store")


async def get(key, *, cache: Cache, db):
    """Return the value for `key`. `await db.read(key)` loads it from the database.

    Stage 1 (cache-aside): try cache.lookup(key); on a miss read the database,
    cache.store() the value, and return it.

    Stage 2 (single-flight): if a load for this key is already in flight
    (cache.loading), await its future instead of reading again; otherwise
    create a future (asyncio.get_running_loop().create_future()), put it in
    cache.loading, do the read, set its result (or exception), and remove it
    when done. Wrap the shared future in asyncio.shield() when awaiting it.
    """
    return await db.read(key)


