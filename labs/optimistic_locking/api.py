"""What your StockService gets: a database of stock rows, each with a value and a version.

    row = await db.read(item)                      SELECT value, version FROM stock WHERE id = item
    row.value, row.version                         the stock count, and how many times it was written
    await db.write(item, value)                    UPDATE stock SET value = ..., version = version + 1
                                                   WHERE id = item           (last write wins)
    await db.compare_and_set(item, value, version) -> bool
                                                   UPDATE stock SET value = ..., version = version + 1
                                                   WHERE id = item AND version = ...
                                                   True if it updated the row (nobody wrote it since
                                                   you read it), False if it matched no row
    raise Conflict(item)                           "someone changed it first, try again" (HTTP 409)

Every call is a round trip to the database (~3 ms, much more when the network is slow), so between
your `read` and your `write` other app servers can write the same row. Writes to one row take its
row lock in turn (0.5 ms each), so a write that loses the version check still costs the row time,
and the writes behind it wait.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from contextvars import ContextVar
from typing import NamedTuple

from core.vtime import now

START_STOCK = 1000  # every row's value before anyone writes it

# (request id, delta) of the request being served: the scenario sets it, the database reads it.
current_request: ContextVar[tuple[int, int] | None] = ContextVar("current_request", default=None)

# What one write did (the scenario keeps these).
COMMIT, CONFLICT, CLOBBER = range(3)  # written; matched no row (stale version); written over others


class Row(NamedTuple):
    value: int
    version: int


class Conflict(Exception):
    """The row changed since you read it, and you give up: the client gets HTTP 409."""


class Database:
    """Stock rows with a version each. Each call takes one round trip; the statement itself runs
    half way through it, in one step (like a single UPDATE: nothing runs between its check and its
    write).

    Reads never wait (like MVCC). A write takes the row's lock and holds it for `hold` seconds
    (finding the row, writing it and its WAL record) before it checks and writes, so writes to
    one row queue up behind each other: every write that loses the version check still took its
    turn, and made the writes behind it wait.

    It also watches for lost updates: a plain `write` from a request that read an older version
    than the row has now writes over the updates in between, and they are lost.
    """

    def __init__(self, latency: float = 0.003, rng: random.Random | None = None,
                 on_write: Callable[[tuple[int, int] | None, float, int, int], None] | None = None,
                 hold: float = 0.0005) -> None:
        self.latency = latency
        self.hold = hold
        self._erased: dict[int, set[int]] = {}  # item -> versions a later write erased
        self._free: dict[int, float] = {}  # item -> when its row lock is free again
        self.rng = rng or random.Random(0)
        self.on_write = on_write  # (request, started, result, updates lost) after every write
        self._rows: dict[int, list[int]] = {}  # item -> [value, version]
        self.seen: dict[int, dict[int, int]] = {}  # request id -> {item: version it last read}

    async def _half(self) -> None:
        await asyncio.sleep(self.latency / 2 * (0.8 + 0.4 * self.rng.random()))

    def _row(self, item: int) -> list[int]:
        row = self._rows.get(item)
        if row is None:
            row = self._rows[item] = [START_STOCK, 0]
        return row

    async def read(self, item: int) -> Row:
        who = current_request.get()
        await self._half()
        value, version = self._row(item)
        if who is not None:
            self.seen.setdefault(who[0], {})[item] = version
        await self._half()
        return Row(value, version)

    async def _arrive_and_lock(self, item: int) -> None:
        """Travel to the database, wait for the row's lock (first come, first served) and do the
        work of the write; the caller then checks and writes in one step."""
        arrive = now() + self.latency / 2 * (0.8 + 0.4 * self.rng.random())
        turn = max(arrive, self._free.get(item, 0.0))
        self._free[item] = turn + self.hold
        await asyncio.sleep(turn + self.hold - now())

    async def write(self, item: int, value: int) -> None:
        who, started = current_request.get(), now()
        await self._arrive_and_lock(item)
        row = self._row(item)
        lost = 0
        if who is not None:
            read = self.seen.get(who[0], {}).get(item)
            if read is None:
                lost = int(value != row[0] + who[1])
            else:  # every version written since this request read, not already erased, is erased now
                erased = self._erased.setdefault(item, set())
                fresh = [v for v in range(read + 1, row[1] + 1) if v not in erased]
                lost = len(fresh)
                erased.update(fresh)
                if len(erased) > 512:  # forget old versions
                    erased.difference_update([v for v in erased if v < row[1] - 256])
        row[0], row[1] = value, row[1] + 1
        if who is not None:
            self.seen.setdefault(who[0], {})[item] = row[1]
        await self._half()
        self._log(who, started, CLOBBER if lost > 0 else COMMIT, max(0, lost))

    async def compare_and_set(self, item: int, value: int, version: int) -> bool:
        who, started = current_request.get(), now()
        await self._arrive_and_lock(item)
        row = self._row(item)
        ok = row[1] == version  # the check and the write in one step: atomic
        if ok:
            row[0], row[1] = value, row[1] + 1
            if who is not None:
                self.seen.setdefault(who[0], {})[item] = row[1]
        await self._half()
        self._log(who, started, COMMIT if ok else CONFLICT, 0)
        return ok

    def _log(self, who, started: float, result: int, lost: int) -> None:
        if self.on_write is not None:
            self.on_write(who, started, result, lost)

    def value(self, item: int) -> int:
        """The row's value now (for tests)."""
        return self._row(item)[0]
