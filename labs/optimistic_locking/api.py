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
your `read` and your `write` other app servers can write the same row.
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

    It also watches for lost updates: a plain `write` from a request that read an older version
    than the row has now writes over the updates in between, and they are lost.
    """

    def __init__(self, latency: float = 0.003, rng: random.Random | None = None,
                 on_write: Callable[[tuple[int, int] | None, float, int, int], None] | None = None) -> None:
        self.latency = latency
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

    async def write(self, item: int, value: int) -> None:
        who, started = current_request.get(), now()
        await self._half()
        row = self._row(item)
        lost = 0
        if who is not None:
            read = self.seen.get(who[0], {}).get(item)
            lost = row[1] - read if read is not None else int(value != row[0] + who[1])
        row[0], row[1] = value, row[1] + 1
        if who is not None:
            self.seen.setdefault(who[0], {})[item] = row[1]
        await self._half()
        self._log(who, started, CLOBBER if lost > 0 else COMMIT, max(0, lost))

    async def compare_and_set(self, item: int, value: int, version: int) -> bool:
        who, started = current_request.get(), now()
        await self._half()
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
