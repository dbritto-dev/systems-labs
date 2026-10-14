"""Lab hot_partition: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
import math
import random
from collections import deque

from labs.hot_partition.api import PARTITIONS, Throttled, now, salted

WINDOW = 0.25  # seconds of recent operations heat() counts
HOT = 50.0  # writes/s on one key that make it hot: a third of what a partition can serve
SALTS = PARTITIONS  # stage 1: sub-keys per hot key, one on every partition
PER_SALT = 30.0  # stage 2: writes/s each sub-key should take, at most
COOL = 25.0  # stage 2: writes/s under which a salted key is cool ...
COOL_FOR = 2.0  # ... for this long: fold its sub-keys back into the key
GRACE = 1.0  # stage 2: wait this long after the last write to a sub-key before folding it
READ_HOT = 50.0  # stage 2: reads/s that make a key's reads hot: serve them from the cache
CACHE_TTL = 0.5  # stage 2: seconds a cached count is served


class Counters:
    def __init__(self, store, rng: random.Random | None = None) -> None:
        self.store = store
        self.rng = rng or random.Random(0)
        self.recent: dict[tuple[str, str], deque] = {}  # (key, "w" or "r") -> recent times
        self.width: dict[str, int] = {}  # salted keys: how many sub-keys hold part of the count
        self.writing: dict[str, int] = {}  # salted keys: how many sub-keys new writes go to
        self.calm_since: dict[str, float] = {}
        self.cache: dict[str, tuple[float, int]] = {}

    async def incr(self, key: str) -> None:
        rate = self.heat(key, "w")
        if rate >= HOT:  # write-hot: spread it (wider if it got hotter)
            self.salt(key, rate)
        elif key in self.width:  # salted, and maybe cool again
            self.cool(key, rate)
        await self.store.incr(self.pick(key))

    async def read(self, key: str) -> int:
        hot = self.heat(key, "r") >= READ_HOT or key in self.width  # a fan-in is worth caching too
        if hot:
            cached = self.cache.get(key)
            if cached is not None and now() - cached[0] < CACHE_TTL:
                return cached[1]  # a count at most CACHE_TTL old: no request at all
        value = sum(await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key))))
        if hot:
            self.cache[key] = (now(), value)
        else:
            self.cache.pop(key, None)
        return value

    def keys_of(self, key: str) -> list[str]:
        return [salted(key, i) for i in range(self.width.get(key, 1))]

    def heat(self, key: str, op: str) -> float:
        times = self.recent.setdefault((key, op), deque())
        t = now()
        times.append(t)
        while times[0] <= t - WINDOW:
            times.popleft()
        return len(times) / WINDOW

    def pick(self, key: str) -> str:
        n = self.writing.get(key, 1)
        return salted(key, self.rng.randrange(n)) if n > 1 else key

    def salts_for(self, rate: float) -> int:
        return max(2, min(PARTITIONS, math.ceil(rate / PER_SALT)))

    def salt(self, key: str, rate: float) -> None:
        n = max(self.width.get(key, 1), self.salts_for(rate))  # only ever wider while it is salted
        self.width[key] = self.writing[key] = n
        self.calm_since.pop(key, None)

    def cool(self, key: str, rate: float) -> None:
        if rate >= COOL:
            self.calm_since.pop(key, None)
            return
        since = self.calm_since.setdefault(key, now())
        if now() - since >= COOL_FOR and self.writing[key] > 1:
            self.writing[key] = 1  # new writes go to the key itself again
            asyncio.ensure_future(self.fold(key))

    async def fold(self, key: str) -> None:
        await asyncio.sleep(GRACE)  # writes already on their way to a sub-key land first
        if self.writing.get(key, 1) > 1:
            return  # it got hot again
        for i in range(1, self.width[key]):
            value = await _retry(lambda: self.store.take(salted(key, i)))  # now only in our hands
            if value:
                await _retry(lambda: self.store.incr(key, value))
        if self.writing.get(key, 1) == 1:  # still cool: one key holds the whole count again
            del self.width[key], self.writing[key]
            self.cache.pop(key, None)


async def _retry(call):
    while True:
        try:
            return await call()
        except Throttled:
            await asyncio.sleep(0.05)
