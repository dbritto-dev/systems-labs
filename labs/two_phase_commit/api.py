"""What your nodes get: a database per shard, and a durable log for the coordinator.

Every shard node gets `self.db`, its database on disk. It survives a crash of the node: a restarted
shard gets the same `db` back, with every balance, every prepared transaction and its row locks.

    await db.write(txn, account, delta) -> bool    autocommit: apply it now, or False (stage 0)
    await db.prepare(txn, account, delta) -> bool  vote: lock the row, check it, write a prepare
                                                   record to disk. True = yes (the row stays locked
                                                   until commit or abort); False = no (nothing held)
    db.commit(txn)                                 apply the prepared write, release the row
    db.abort(txn)                                  drop it, release the row (a later prepare of it
                                                   says no)
    db.in_doubt() -> {txn: prepared_at}            prepared, and not yet committed or aborted
    db.balance(account) -> int

A prepare (or a write) says no when the row stays locked by another prepared transaction for
LOCK_TIMEOUT seconds (a lock timeout), or when a constraint fails. commit and abort of a
transaction that is not prepared here do nothing, so a duplicate is harmless.

The coordinator gets `self.log`, a decision log on disk. It survives a crash of the coordinator.

    await log.write(txn, decision, shards)   durable once it returns (an fsync, ~2 ms)
    log.read(txn) -> decision or None
    log.items() -> [(txn, decision, shards)]
    log.forget(txn)                          once every shard has the decision

Everything else on your nodes lives in memory, and a crash loses it.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable

from core.vtime import now

LOCK_TIMEOUT = 0.3  # seconds a prepare (or a write) waits for a locked row before it says no
FSYNC = 0.002  # seconds to make a record durable

# What happened to a transaction on a shard (the scenario listens).
PREPARED, APPLIED, RELEASED, REFUSED = range(4)


class Crashed(BaseException):
    """This node is dead: its disk calls go nowhere. Not an Exception on purpose."""


class Life:
    """Whether one run of a node (one process) is alive. A restart is a new Life."""

    __slots__ = ("dead",)

    def __init__(self) -> None:
        self.dead = False

    def check(self) -> None:
        if self.dead:
            raise Crashed()


class ShardDB:
    """One shard's tables on disk: balances, prepare records and row locks."""

    def __init__(self, index: int, balances: dict[str, int],
                 on_event: Callable[[int, int, str, float, int], None] | None = None) -> None:
        self.index = index
        self.balances = dict(balances)
        self.on_event = on_event or (lambda *a: None)
        self.prepared: dict[str, tuple[str, int, float]] = {}  # txn -> (account, delta, since)
        self.locks: dict[str, str] = {}  # account -> txn holding it
        self.waiters: dict[str, deque] = {}  # account -> futures waiting for it
        self.outcome: dict[str, str] = {}  # txn -> "commit" / "abort" (kept a while)
        self._aged: deque[tuple[float, str]] = deque()
        # The scenario's incidents: how long to wait before saying no (None = say yes).
        self.refuse: Callable[[str], float | None] = lambda txn: None

    # ---- the row locks

    async def _lock(self, txn: str, account: str) -> bool:
        """Take the row for txn, waiting up to LOCK_TIMEOUT for the transaction holding it."""
        holder = self.locks.get(account)
        if holder is None or holder == txn:
            self.locks[account] = txn
            return True
        fut = asyncio.get_running_loop().create_future()
        queue = self.waiters.setdefault(account, deque())
        queue.append((txn, fut))
        try:
            async with asyncio.timeout(LOCK_TIMEOUT):
                await fut
        except TimeoutError:
            pass
        except BaseException:  # the node died while waiting: let the row go if it was handed over
            if self.locks.get(account) == txn:
                self._unlock(account)
            raise
        finally:
            if (txn, fut) in queue:
                queue.remove((txn, fut))
        return self.locks.get(account) == txn

    def _unlock(self, account: str) -> None:
        """Release the row and hand it to the first transaction waiting for it."""
        self.locks.pop(account, None)
        queue = self.waiters.get(account)
        while queue:
            txn, fut = queue.popleft()
            if not fut.done():
                self.locks[account] = txn
                fut.set_result(None)
                return

    def _remember(self, txn: str, outcome: str) -> None:
        self.outcome[txn] = outcome
        t = now()
        self._aged.append((t, txn))
        while self._aged and self._aged[0][0] < t - 120.0:
            self.outcome.pop(self._aged.popleft()[1], None)

    # ---- what the nodes call (through a View)

    async def write(self, txn: str, account: str, delta: int) -> bool:
        wait = self.refuse(txn)
        if wait is not None:
            await asyncio.sleep(wait)
            self.on_event(REFUSED, self.index, txn, now(), 0)
            return False
        if not await self._lock(txn, account):
            self.on_event(REFUSED, self.index, txn, now(), 0)
            return False
        try:
            if self.balances.get(account, 0) + delta < 0:
                self.on_event(REFUSED, self.index, txn, now(), 0)
                return False
            await asyncio.sleep(FSYNC)
            self.balances[account] = self.balances.get(account, 0) + delta
            self.on_event(APPLIED, self.index, txn, now(), delta)
            return True
        finally:
            if self.locks.get(account) == txn:
                self._unlock(account)

    async def prepare(self, txn: str, account: str, delta: int) -> bool:
        if txn in self.prepared:
            return True  # a duplicate prepare: still yes
        if txn in self.outcome:
            return self.outcome[txn] == "commit"
        wait = self.refuse(txn)
        if wait is not None:
            await asyncio.sleep(wait)
            self.on_event(REFUSED, self.index, txn, now(), 0)
            return False
        got = False
        try:
            got = await self._lock(txn, account)
            if not got or txn in self.outcome or self.balances.get(account, 0) + delta < 0:
                if got:
                    self._unlock(account)
                    got = False
                self.on_event(REFUSED, self.index, txn, now(), 0)
                return False
            await asyncio.sleep(FSYNC)  # the prepare record reaches the disk
            if txn in self.outcome:  # aborted while it was being written: vote no after all
                self._unlock(account)
                got = False
                self.on_event(REFUSED, self.index, txn, now(), 0)
                return False
        except BaseException:
            if got and self.locks.get(account) == txn:
                self._unlock(account)  # it died before the record was durable: nothing held
            raise
        self.prepared[txn] = (account, delta, now())
        self.on_event(PREPARED, self.index, txn, now(), 0)
        return True

    def commit(self, txn: str) -> None:
        entry = self.prepared.pop(txn, None)
        if entry is None:
            return
        account, delta, _ = entry
        self.balances[account] = self.balances.get(account, 0) + delta
        self._remember(txn, "commit")
        self.on_event(APPLIED, self.index, txn, now(), delta)
        self.on_event(RELEASED, self.index, txn, now(), 1)
        if self.locks.get(account) == txn:
            self._unlock(account)

    def abort(self, txn: str) -> None:
        entry = self.prepared.pop(txn, None)
        if txn not in self.outcome:  # aborting a committed transaction does nothing
            self._remember(txn, "abort")
        if entry is None:
            return
        self.on_event(RELEASED, self.index, txn, now(), 0)
        if self.locks.get(entry[0]) == txn:
            self._unlock(entry[0])

    def in_doubt(self) -> dict[str, float]:
        return {txn: since for txn, (_, _, since) in self.prepared.items()}

    def balance(self, account: str) -> int:
        return self.balances.get(account, 0)

    def view(self, life: Life) -> "ShardView":
        return ShardView(self, life)


class ShardView:
    """A shard's database as one run of its node sees it: calls from a dead node raise Crashed."""

    __slots__ = ("_db", "_life")

    def __init__(self, db: ShardDB, life: Life) -> None:
        self._db, self._life = db, life

    async def write(self, txn: str, account: str, delta: int) -> bool:
        self._life.check()
        return await self._db.write(txn, account, delta)

    async def prepare(self, txn: str, account: str, delta: int) -> bool:
        self._life.check()
        return await self._db.prepare(txn, account, delta)

    def commit(self, txn: str) -> None:
        self._life.check()
        self._db.commit(txn)

    def abort(self, txn: str) -> None:
        self._life.check()
        self._db.abort(txn)

    def in_doubt(self) -> dict[str, float]:
        self._life.check()
        return self._db.in_doubt()

    def balance(self, account: str) -> int:
        return self._db.balance(account)


class DecisionLog:
    """The coordinator's log on disk: it survives a crash of the coordinator."""

    def __init__(self) -> None:
        self.data: dict[str, tuple[str, list[str]]] = {}

    def view(self, life: Life) -> "LogView":
        return LogView(self, life)


class LogView:
    """The decision log as one run of the coordinator sees it."""

    __slots__ = ("_log", "_life")

    def __init__(self, log: DecisionLog, life: Life) -> None:
        self._log, self._life = log, life

    async def write(self, txn: str, decision: str, shards: list[str]) -> None:
        self._life.check()
        await asyncio.sleep(FSYNC)
        self._life.check()  # it died during the fsync: the record never made it
        self._log.data[txn] = (decision, list(shards))

    def read(self, txn: str) -> str | None:
        self._life.check()
        entry = self._log.data.get(txn)
        return entry[0] if entry else None

    def items(self) -> list[tuple[str, str, list[str]]]:
        self._life.check()
        return [(txn, d, list(shards)) for txn, (d, shards) in self._log.data.items()]

    def forget(self, txn: str) -> None:
        self._life.check()
        self._log.data.pop(txn, None)

    def __len__(self) -> int:
        return len(self._log.data)
