"""Lab cache_invalidation: YOUR FILE. Edit it and save; the live window reruns it.

Three app servers show product pages (price, stock) from one shared cache in front of the database.
Reads are many; writes come from checkouts, admins and import jobs. Right now `update` writes the
cache first and the database second: when the database refuses the write (a lock timeout), the
cache keeps a price that was never saved; when two writers overlap, the cache ends with one's value
and the database with the other's. Nothing fixes it until the TTL (5 minutes) runs out.

Do the stages in order, in this file:

  Stage 1  Cache-aside: in `update`, write the database first, then DELETE the key (do not set it):
           the next read misses and loads the new record. No more prices that were never saved.
           But a race remains: a read misses, loads the OLD record, stalls (a GC pause, a slow
           reply), and stores it AFTER a writer has written the database and deleted the key.
           That stale entry stays until the TTL.
  Stage 2  Leases, as at Facebook: in `read`, ask `cache.lease_get(key)`. A miss gives you a token;
           load the record and store it with `cache.lease_set(key, record, token, TTL)`. A delete
           (or set) of the key in between makes the token invalid, and the cache refuses the late,
           stale fill. Keep a short TTL (30 s) as a safety net for anything else that goes wrong.

What you get (see labs/cache_invalidation/api.py):
  record = await self.db.read(key)          await self.db.write(key, record)  (may raise WriteFailed)
  record = await self.cache.get(key)        await self.cache.set(key, record, ttl)
  await self.cache.delete(key)
  lease = await self.cache.lease_get(key)   lease.value (a hit) or lease.token (a miss)
  ok = await self.cache.lease_set(key, record, lease.token, ttl)

A lock in one app server does not help: the other app servers do not see it.

Check yourself:  uv run pytest labs/cache_invalidation
Peek at a solution (after trying!):  labs/cache_invalidation/reference.py
"""

from __future__ import annotations

TTL = 300.0  # seconds a cached record lives. Stage 2: make it short (30 s), a safety net


class ProductCache:
    """Reads and writes product records through the shared cache.

    Contract:
      - `await read(key)` returns the product's record: from the cache when it is there, else from
        the database (and then keep it in the cache for the next readers).
      - `await update(key, record)` saves the record; when it returns, every read that starts
        afterwards must see it (or something newer). If the database refuses the write, raise.
      - Never leave a record in the cache that is older than the database's (or never saved).
    """

    def __init__(self, cache, db) -> None:
        self.cache = cache
        self.db = db

    async def read(self, key: int):
        # Stage 2: lease = await self.cache.lease_get(key); if lease.value is not None, return it.
        #          Otherwise read the database and `await self.cache.lease_set(key, record,
        #          lease.token, TTL)`; return the record whether the cache took it or not.
        record = await self.cache.get(key)
        if record is not None:
            return record
        record = await self.db.read(key)
        await self.cache.set(key, record, TTL)  # may land after a writer's delete: stale until TTL
        return record

    async def update(self, key: int, record) -> None:
        # Stage 1: write the database first (if it raises, the cache is untouched), then
        #          `await self.cache.delete(key)`.
        await self.cache.set(key, record, TTL)  # readers see it now...
        await self.db.write(key, record)  # ...but if this raises, or another writer commits in between?
