"""Lab cache_invalidation: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

TTL = 30.0  # short: a safety net for a delete that never arrived, not the way to be fresh


class ProductCache:
    def __init__(self, cache, db) -> None:
        self.cache = cache
        self.db = db

    async def read(self, key: int):
        lease = await self.cache.lease_get(key)
        if lease.value is not None:
            return lease.value
        record = await self.db.read(key)
        # The cache takes it only if nobody deleted (or set) the key since our miss: a writer that
        # committed after our read has deleted it, so this record is old and is refused.
        await self.cache.lease_set(key, record, lease.token, TTL)
        return record

    async def update(self, key: int, record) -> None:
        # The database first: if it refuses, the cache never saw the record. Then delete, never set:
        # a set races with other writers; a delete only makes the next reader load the truth.
        await self.db.write(key, record)
        await self.cache.delete(key)
