"""What your code gets: a database with transactions, a message broker, and ids.

    db.transaction()                     an `async with` block: everything you write inside it is
                                         committed together when the block ends, or not at all
                                         (an exception, or the process being killed, rolls it back)
      await tx.insert(table, row)        row is a dict with an "id"; raises DuplicateKey if the id
                                         is already there (a primary key)
      await tx.get(table, id)            the row, or None (it sees the transaction's own writes)
    leaving the block commits; the commit itself can fail with CommitFailed (a deadlock, a
    serialization failure, a lock timeout): then nothing was written

    await db.fetch_unsent(limit)         outbox rows not marked sent yet, oldest first (at most limit)
    await db.mark_sent(ids)              marks those outbox rows sent (they are not fetched again)

    await broker.publish(event)          appends the event to the topic; raises BrokerUnavailable
                                         when the broker is down (nothing was published then)

    new_id(prefix) -> str                a fresh unique id, e.g. "evt-123"

Every call to the orders database takes about a millisecond (a commit a few), so another request can
run in between.
Old rows are archived after ARCHIVE seconds, so the tables do not grow forever.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from core.vtime import now

ARCHIVE = 600.0  # seconds a row stays in a table

_ids = itertools.count(1)


def new_id(prefix: str) -> str:
    """A fresh unique id, like a UUID: new_id("evt") -> "evt-41"."""
    return f"{prefix}-{next(_ids)}"


class DuplicateKey(Exception):
    """A row with this id is already in the table (a primary key violation)."""


class CommitFailed(Exception):
    """The database refused the commit (deadlock, serialization failure, lock timeout): nothing was written."""


class BrokerUnavailable(Exception):
    """The broker cannot take messages right now: nothing was published."""


class ProcessKilled(BaseException):
    """The process was killed (SIGKILL): no more code of it runs, not even `finally` blocks that
    talk to the database or the broker. Not an Exception, so `except Exception` does not catch it."""


class Process:
    """One running process (the order service's pod, the shipping consumer). The scenario kills it."""

    def __init__(self) -> None:
        self.dead = False


# The process the running code belongs to: the scenario sets it for each task.
current_process: ContextVar[Process | None] = ContextVar("current_process", default=None)


async def _pause(seconds: float) -> None:
    """Take this long (an in-memory database with latency 0 answers without waiting)."""
    if seconds > 0:
        await asyncio.sleep(seconds)
    _check()


def _check() -> None:
    p = current_process.get()
    if p is not None and p.dead:
        raise ProcessKilled()


class Database:
    """A small transactional database. Tables are created on first use; every row has an "id"."""

    def __init__(self, latency: float = 0.001, commit_latency: float = 0.003,
                 on_commit: Callable[[dict[str, list[dict]]], None] | None = None,
                 on_fetch: Callable[[int], None] | None = None) -> None:
        self.latency = latency
        self.commit_latency = commit_latency
        self.on_commit = on_commit  # the scenario watches what gets committed
        self.on_fetch = on_fetch
        self.fail_commit: Callable[[], bool] = lambda: False  # set by the scenario in an incident
        self.tables: dict[str, OrderedDict[str, tuple[dict, float]]] = {}
        self._unsent: OrderedDict[str, dict] = OrderedDict()  # outbox rows not sent yet
        self._next_archive = 0.0

    def _table(self, name: str) -> OrderedDict[str, tuple[dict, float]]:
        return self.tables.setdefault(name, OrderedDict())

    def transaction(self) -> "Transaction":
        return Transaction(self)

    @property
    def unsent(self) -> int:
        """Outbox rows waiting to be sent (for the scenario's gauges)."""
        return len(self._unsent)

    async def get(self, table: str, key: str) -> dict | None:
        await _pause(self.latency)
        item = self._table(table).get(key)
        return None if item is None else item[0]

    async def fetch_unsent(self, limit: int) -> list[dict]:
        """SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT limit."""
        await _pause(self.latency * 2)
        rows = list(itertools.islice(self._unsent.values(), max(0, int(limit))))
        if self.on_fetch is not None:
            self.on_fetch(len(rows))
        return [dict(r) for r in rows]

    async def mark_sent(self, ids) -> None:
        """UPDATE outbox SET sent_at = now() WHERE id IN (ids)."""
        ids = list(ids)
        await _pause(self.latency * 2)
        for key in ids:
            self._unsent.pop(key, None)

    def _apply(self, writes: dict[str, dict[str, dict]]) -> None:
        t = now()
        for table, rows in writes.items():
            tab = self._table(table)
            for key, row in rows.items():
                if key in tab:  # someone else committed this id first
                    raise DuplicateKey(f"{table}: {key}")
            for key, row in rows.items():
                tab[key] = (row, t)
                if table == "outbox":
                    self._unsent[key] = row
        if t >= self._next_archive:
            self._next_archive = t + 5.0
            for tab in self.tables.values():
                while tab:
                    key, (_, at) = next(iter(tab.items()))
                    if at > t - ARCHIVE:
                        break
                    del tab[key]


class Transaction:
    """One database transaction: `async with db.transaction() as tx:`."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.writes: dict[str, dict[str, dict]] = {}
        self.done = False

    async def __aenter__(self) -> "Transaction":
        _check()  # BEGIN (sent with the first statement)
        return self

    async def __aexit__(self, kind, exc, tb) -> bool:
        if kind is None:
            await self.commit()
        else:
            self.writes = {}  # ROLLBACK: nothing was written
            self.done = True
        return False

    async def insert(self, table: str, row: dict) -> None:
        if self.done:
            raise RuntimeError("this transaction has already ended")
        key = row["id"]
        await _pause(self.db.latency)
        if key in self.db._table(table) or key in self.writes.get(table, {}):
            raise DuplicateKey(f"{table}: {key}")
        self.writes.setdefault(table, {})[key] = dict(row)

    async def get(self, table: str, key: str) -> dict | None:
        await _pause(self.db.latency)
        mine = self.writes.get(table, {}).get(key)
        if mine is not None:
            return mine
        item = self.db._table(table).get(key)
        return None if item is None else item[0]

    async def commit(self) -> None:
        if self.done:
            return
        await _pause(self.db.commit_latency)  # COMMIT: write the log, fsync
        self.done = True
        writes, self.writes = self.writes, {}
        if self.db.fail_commit():
            raise CommitFailed("could not serialize access due to concurrent update")
        self.db._apply(writes)
        if self.db.on_commit is not None:
            self.db.on_commit({t: list(rows.values()) for t, rows in writes.items()})


class Broker:
    """A topic on a message broker (like Kafka): an append-only log the consumers read in order."""

    def __init__(self, latency: float = 0.001,
                 on_publish: Callable[[dict, bool], None] | None = None) -> None:
        self.latency = latency
        self.down = False  # set by the scenario in an incident
        self.log: list[dict] = []
        self.base = 0  # offset of log[0] (old messages are trimmed)
        self.on_publish = on_publish

    async def publish(self, event: dict) -> None:
        await asyncio.sleep(self.latency * (20 if self.down else 1))  # a refused connection takes longer
        _check()
        if self.down:
            if self.on_publish is not None:
                self.on_publish(event, False)
            raise BrokerUnavailable("no leader for the partition")
        self.log.append(dict(event))
        if self.on_publish is not None:
            self.on_publish(event, True)

    @property
    def end(self) -> int:
        return self.base + len(self.log)

    def read(self, offset: int) -> dict:
        return self.log[offset - self.base]

    def trim(self, before: int) -> None:
        """Forget messages before offset `before` (retention)."""
        cut = max(0, min(before - self.base, len(self.log)))
        if cut:
            del self.log[:cut]
            self.base += cut
