"""What your PaymentService gets: a ledger that moves money, and a key store that remembers keys.

    ledger.insert(account, amount) -> charge_id     charges the card (slow: ~20 ms, much more
                                                    when the database struggles)
    await store.get(key) -> value or None           like Redis GET
    await store.set(key, value, ttl)                like Redis SET ... EX ttl
    await store.add(key, value, ttl) -> bool        like Redis SET ... NX EX ttl: stores it only if
                                                    the key is new, in one step; True if it did
    raise Conflict(key)                             "this key is being processed, retry later" (409)

Every call to the store takes ~1 ms, so `get` followed by `set` is two steps, and another
request can run in between.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from core.vtime import now

IN_PROGRESS = "in-progress"  # a value you can store while a charge is running

# (payment id, attempt) of the request being served: the scenario sets it, the ledger reads it.
current_attempt: ContextVar[tuple[int, int] | None] = ContextVar("current_attempt", default=None)


class Conflict(Exception):
    """The same key is being processed right now: the client retries a little later (HTTP 409)."""


class Ledger:
    """Where charges happen. Every insert is a new charge, even for the same payment."""

    def __init__(self, latency: float = 0.02, rng: random.Random | None = None,
                 on_charge: Callable[[tuple[int, int] | None, int], None] | None = None) -> None:
        self.latency = latency
        self.rng = rng or random.Random(0)
        self.on_charge = on_charge
        self._ids = itertools.count(1)

    async def insert(self, account: int, amount: int) -> int:
        who = current_attempt.get()
        await asyncio.sleep(self.latency * (0.8 + 0.4 * self.rng.random()))
        charge_id = next(self._ids)
        if self.on_charge is not None:
            self.on_charge(who, charge_id)
        return charge_id


class KeyStore:
    """A key/value store with expiry, like Redis. Each call takes ~1 ms."""

    def __init__(self, latency: float = 0.001) -> None:
        self.latency = latency
        self._data: dict[str, tuple[Any, float]] = {}  # key -> (value, expires at)
        self._next_purge = 0.0

    def _live(self, key: str) -> Any:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if now() >= expires:
            del self._data[key]
            return None
        return value

    def _purge(self) -> None:
        if now() >= self._next_purge:
            self._next_purge = now() + 5.0
            dead = [k for k, (_, e) in self._data.items() if e <= now()]
            for k in dead:
                del self._data[k]

    def __len__(self) -> int:
        return len(self._data)

    async def get(self, key: str) -> Any:
        await asyncio.sleep(self.latency)
        return self._live(key)

    async def set(self, key: str, value: Any, ttl: float) -> None:
        await asyncio.sleep(self.latency)
        self._purge()
        self._data[key] = (value, now() + ttl)

    async def add(self, key: str, value: Any, ttl: float) -> bool:
        await asyncio.sleep(self.latency)
        self._purge()
        if self._live(key) is not None:
            return False
        self._data[key] = (value, now() + ttl)  # no await between the check and the write: atomic
        return True
