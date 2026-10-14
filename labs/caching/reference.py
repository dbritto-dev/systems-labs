"""Lab caching: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
import random

from core.vtime import now


class Cache:
    def __init__(self, ttl: float = 30.0, rng: random.Random | None = None) -> None:
        self.ttl = ttl
        self.rng = rng or random.Random(0)
        self.data: dict = {}  # key -> (value, expires at)
        self.loading: dict = {}  # key -> future of the load in flight

    def clear(self) -> None:
        self.data.clear()

    def lookup(self, key):
        hit = self.data.get(key)
        if hit is None:
            return None
        value, expires = hit
        if now() >= expires:
            del self.data[key]
            return None
        return value

    def store(self, key, value) -> None:
        # Jitter: keys loaded together do not all expire together.
        self.data[key] = (value, now() + self.ttl * self.rng.uniform(0.8, 1.2))


async def get(key, *, cache: Cache, db):
    value = cache.lookup(key)
    if value is not None:
        return value
    pending = cache.loading.get(key)
    if pending is not None:
        # Single-flight: someone is already loading this key; wait for them.
        return await asyncio.shield(pending)
    fut = asyncio.get_running_loop().create_future()
    cache.loading[key] = fut
    try:
        value = await db.read(key)
        cache.store(key, value)
        fut.set_result(value)
        return value
    except BaseException as exc:
        fut.set_exception(exc)
        fut.exception()  # mark it retrieved, even if nobody else was waiting
        raise
    finally:
        del cache.loading[key]
