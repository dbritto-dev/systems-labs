"""What your Counters gets: a key/value store sharded over 6 partitions by hash of the key.

Think of DynamoDB, Cassandra or a sharded Redis: every key lives on one partition, picked by a
hash of the key, and every partition is a server that can only do so much.

    PARTITIONS                      6: p0 ... p5
    home(key) -> int                the partition a key lives on: stable_hash(key) % PARTITIONS
    salted(key, i) -> str           sub-key i of key, "key#i". salted(key, 0) is key itself. The
                                    store puts sub-key i on the partition i places after the key's
                                    home, so sub-keys 0 ... 5 sit on six different partitions
                                    (like HBase's salt prefixes, or Cassandra's bucket columns).
    await store.incr(key, n=1)      add n to the counter at key (0 if it was never written)
    await store.get(key) -> int     read the counter at key
    await store.take(key) -> int    read the counter at key and set it to 0, in one request

Every call is one request to one partition. A partition serves CAPACITY requests a second, one at
a time, in arrival order (each takes 1/CAPACITY seconds). When its queue already holds more than
MAX_WAIT seconds of work, it refuses the request at once: the call raises Throttled, and nothing
was written (DynamoDB's ProvisionedThroughputExceededException).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Callable
from contextvars import ContextVar

from core.vtime import now

PARTITIONS = 6
CAPACITY = 150.0  # requests a second one partition serves
SERVICE = 1.0 / CAPACITY  # seconds one request takes on its partition
MAX_WAIT = 0.2  # seconds of queued work above which a partition throttles
NET = 0.001  # one way, client to partition
TICK = 0.002  # answers arrive on this grid

__all__ = ["CAPACITY", "MAX_WAIT", "PARTITIONS", "Store", "Throttled", "home", "now", "salted", "stable_hash"]


class Throttled(Exception):
    """The partition is overloaded: the request was refused, and nothing was written."""


def stable_hash(text: str) -> int:
    """A 64-bit hash that is the same in every process and every run (unlike Python's hash())."""
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


_HOMES: dict[str, int] = {}


def salted(key: str, i: int) -> str:
    """Sub-key i of key: key itself for i == 0, else "key#i"."""
    return key if i == 0 else f"{key}#{i}"


def base_of(key: str) -> tuple[str, int]:
    """(key, i) for a sub-key made by salted(key, i)."""
    head, sep, tail = key.rpartition("#")
    if sep and tail.isdigit():
        return head, int(tail)
    return key, 0


def home(key: str) -> int:
    """The partition a key lives on. A sub-key salted(key, i) lives i partitions after key's home."""
    p = _HOMES.get(key)
    if p is None:
        base, i = base_of(key)
        p = (stable_hash(base) + i) % PARTITIONS
        if len(_HOMES) < 200_000:
            _HOMES[key] = p
    return p


class Op:
    """One client operation (an incr or a read): counts the store requests it made."""

    __slots__ = ("requests", "done")

    def __init__(self) -> None:
        self.requests = 0
        self.done = False  # requests made after the operation returned are background work


CURRENT: ContextVar[Op | None] = ContextVar("hot_partition_op", default=None)

# What a store request was for, as the screen colours it: a user's request, one on a hot key, an extra
# request of the same operation (a read fanning in), or background work (folding sub-keys back).
PLAIN, HOT, FAN, FOLD = range(4)


class Store:
    """The sharded store. Partitions are single servers with a queue (a `free_at` time each)."""

    def __init__(self, on_request: Callable[[float, int, int, bool, int], None] | None = None,
                 hot_index: Callable[[str], int] | None = None) -> None:
        self.values: dict[str, int] = {}
        self.free_at = [0.0] * PARTITIONS
        self.on_request = on_request  # (t, partition, kind, served, hot) for every request
        self.hot_index = hot_index or (lambda key: -1)  # which incident's key it is, else -1

    async def _request(self, key: str) -> None:
        """One request on the key's partition: wait in its queue, or raise Throttled if that queue
        is too long. Returns once the partition has served it (the caller then applies it)."""
        p = home(key)
        op = CURRENT.get()
        if op is not None and op.done:
            op = None
        if op is not None:
            op.requests += 1
        t = now() + NET  # when it reaches the partition
        start = self.free_at[p] if self.free_at[p] > t else t
        hot = self.hot_index(key) if self.on_request is not None else -1
        kind = FOLD if op is None else FAN if op.requests > 1 else HOT if hot >= 0 else PLAIN
        if start - t > MAX_WAIT:
            if self.on_request is not None:
                self.on_request(t, p, kind, False, hot)
            await asyncio.sleep(2 * NET)
            raise Throttled(f"partition p{p} is overloaded")
        self.free_at[p] = start + SERVICE
        if self.on_request is not None:
            self.on_request(t, p, kind, True, hot)
        # Answers land on a 2 ms grid: many requests wake together (a faster simulation).
        await asyncio.sleep(math.ceil((start + SERVICE + NET) / TICK) * TICK - now())

    async def incr(self, key: str, n: int = 1) -> None:
        await self._request(key)
        self.values[key] = self.values.get(key, 0) + n

    async def get(self, key: str) -> int:
        await self._request(key)
        return self.values.get(key, 0)

    async def take(self, key: str) -> int:
        await self._request(key)
        return self.values.pop(key, 0)

    # ---- for the scenario (no request, no time): what the store holds right now

    def peek(self, key: str) -> int:
        return self.values.get(key, 0)
