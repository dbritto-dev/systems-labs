"""Lab hot_partition: YOUR FILE. Edit it and save; the live window reruns it.

A key/value store is sharded over six partitions (p0 ... p5) by a hash of the key; each one serves
150 requests a second. Users like, click and view things: every like is `Counters.incr(key)` and
every view of a count is `Counters.read(key)`, ~120 operations a second over 5,000 keys. Spread
over six partitions that is easy: each one is ~15% busy.

Then one key explodes: a celebrity's post goes viral, a newsletter link is clicked by everyone, a
flash sale sells one product, a bot hammers one id. Hashing spreads keys, not traffic: every
operation on that key lands on the same partition. It throttles and times out, while the other
five idle.

Right now `Counters` sends every operation to the key itself.

Do the stages in order, in this file:

  Stage 1  Split hot keys. Count each key's recent writes (`heat`); when a key gets hot, salt it:
           spread its writes over SALTS sub-keys, salted(key, 0) ... salted(key, SALTS - 1), which
           the store puts on different partitions. A read must now add up every sub-key:
           `keys_of(key)` names them, and `read` sums them (the fan-in).
  Stage 2  Adaptive. Salt only while it is hot, with N from the heat (`salts_for`); cache the
           count of a hot key for CACHE_TTL, so its reads stop hitting the partitions; and when
           the key cools down, fold its sub-keys back into the key (`cool`, `fold`), so its reads
           stop fanning in. Never lose an increment.

What you get (see labs/hot_partition/api.py):
  salted(key, i)                  sub-key i of key: "key#i"; salted(key, 0) is key itself. Sub-key i
                                  lives i partitions after key's home, so 0 ... 5 are all different
  await store.incr(key, n=1)      add n to a counter
  await store.get(key) -> int     read a counter (0 if never written)
  await store.take(key) -> int    read a counter and set it to 0, in one request
  now()                           the clock, in seconds
Every store call is one request to one partition. An overloaded partition raises Throttled.

Check yourself:  uv run pytest labs/hot_partition
Peek at a solution (after trying!):  labs/hot_partition/reference.py
"""

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
    """Counters (likes, clicks, units sold) on the sharded store. Every user operation calls it.

    Contract:
      - `await incr(key)` adds 1 to key's count. When it returns, the increment is acknowledged:
        the store must hold it. If the store raises Throttled, let it raise (the user sees an error).
      - `await read(key)` returns key's count. It may be a little old (at most CACHE_TTL).
      - `keys_of(key)` lists every key in the store that holds part of key's count right now. It is
        checked: the counts in those keys must add up to exactly the increments acknowledged.
      - Hot keys: no partition should be over 90% busy, and when nothing is hot, an operation
        should cost one request, not a fan-in.
    """

    def __init__(self, store, rng: random.Random | None = None) -> None:
        self.store = store
        self.rng = rng or random.Random(0)  # for pick(): runs repeat
        self.recent: dict[tuple[str, str], deque] = {}  # (key, "w" or "r") -> recent times, for heat()
        self.width: dict[str, int] = {}  # salted keys: how many sub-keys hold part of the count
        self.writing: dict[str, int] = {}  # salted keys: how many sub-keys new writes go to
        self.calm_since: dict[str, float] = {}  # salted keys: when they went under COOL (stage 2)
        self.cache: dict[str, tuple[float, int]] = {}  # hot keys: (when, count) (stage 2)

    async def incr(self, key: str) -> None:
        # Stage 1: `rate = self.heat(key, "w")`; when `rate >= HOT`, `self.salt(key, rate)`.
        #          Then write to `self.pick(key)` instead of key.
        # Stage 2: when it is not hot but salted (`key in self.width`), `self.cool(key, rate)`.
        await self.store.incr(key)

    async def read(self, key: str) -> int:
        # Stage 1: nothing to do here once keys_of names every sub-key: this already adds them up.
        # Stage 2: a key is read-hot when `self.heat(key, "r") >= READ_HOT`, or when it is salted.
        #          For a read-hot key, return `self.cache[key]`'s count if it is under CACHE_TTL old;
        #          otherwise read it as below and keep `self.cache[key] = (now(), value)`.
        values = await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key)))
        return sum(values)

    def keys_of(self, key: str) -> list[str]:
        """Every key that holds part of key's count right now: key alone, or all its sub-keys.

        Stage 1: `[salted(key, i) for i in range(self.width.get(key, 1))]`.
        """
        return [key]

    def heat(self, key: str, op: str) -> float:
        """Stage 1. Note one operation on key (op is "w" for a write, "r" for a read) and return
        how many of them it had per second over the last WINDOW seconds, this one included.

        Keep the times in a deque, `self.recent.setdefault((key, op), deque())`: append now(),
        drop the ones older than WINDOW from the left, and return len / WINDOW.
        """
        raise NotImplementedError("TODO stage 1: heat(key, op)")

    def pick(self, key: str) -> str:
        """Stage 1. The key a write goes to: key itself when it is not salted, else one of its
        `self.writing[key]` sub-keys at random (`salted(key, self.rng.randrange(n))`)."""
        raise NotImplementedError("TODO stage 1: pick(key)")

    def salt(self, key: str, rate: float) -> None:
        """Stage 1. The key is hot: spread it. Set `self.width[key]` and `self.writing[key]` to SALTS.

        Stage 2: use `self.salts_for(rate)` instead, but never make it narrower than it already is
        (a read must still add up every sub-key written so far), and forget `self.calm_since[key]`.
        """
        raise NotImplementedError("TODO stage 1: salt(key, rate)")

    def salts_for(self, rate: float) -> int:
        """Stage 2. How many sub-keys a key with `rate` writes/s needs: rate / PER_SALT, rounded up,
        at least 2 and at most PARTITIONS (more would put two sub-keys on one partition)."""
        raise NotImplementedError("TODO stage 2: salts_for(rate)")

    def cool(self, key: str, rate: float) -> None:
        """Stage 2. A salted key that is not hot. While `rate >= COOL`, forget `self.calm_since[key]`.
        Under COOL, remember since when; once it has been calm for COOL_FOR seconds, send new writes
        to the key itself (`self.writing[key] = 1`) and start `self.fold(key)` as a task
        (`asyncio.ensure_future`): this call must not wait for it."""
        raise NotImplementedError("TODO stage 2: cool(key, rate)")

    async def fold(self, key: str) -> None:
        """Stage 2. Move the sub-keys' counts back into the key, without losing one.

        First `await asyncio.sleep(GRACE)`: writes already on their way to a sub-key land. If the
        key got hot again meanwhile (`self.writing[key] > 1`), stop. Else for each sub-key i from 1:
        `value = await self.store.take(salted(key, i))`, then `await self.store.incr(key, value)`
        (retry both on Throttled: a value you took is only in your hands). Finally, if it is still
        cool, forget `self.width[key]` and `self.writing[key]`: reads stop fanning in.
        """
        raise NotImplementedError("TODO stage 2: fold(key)")
