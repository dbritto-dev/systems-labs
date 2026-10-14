"""What your Payments service gets: the ledger's row locks, the ledger itself, and the audit log.

    await locks.acquire(account)                 SELECT ... FROM accounts WHERE id = account FOR UPDATE
                                                 waits (in line, first come first served) while another
                                                 transfer holds the account, however long that takes
    await locks.acquire(account, timeout=0.05)   the same, but gives up after waiting 0.05 s: raises
                                                 LockTimeout (like SET lock_timeout = '50ms')
    locks.release(account)                       let the next transfer in line have it
    locks.release_all()                          release every lock this transfer holds (a ROLLBACK)
    locks.holding()                              the accounts this transfer holds, in the order it got them

    await ledger.move(src, dst, amount)          read both balances, then write src - amount and
                                                 dst + amount in one commit. Hold BOTH locks first:
                                                 anybody who writes either account in between is
                                                 written over (and that money appears or disappears)
    await ledger.apply(entries)                  the same for a batch: entries = [(account, delta)],
                                                 the deltas add up to 0. Hold every account's lock.

    await audit.record(entries)                  append the entries to the audit log (a separate store),
                                                 one row each: 2-6 ms a row, and now and then much
                                                 longer (a disk stall)

Every call is a round trip (~1 ms to the lock manager, ~2 ms to the ledger). Like MySQL with
innodb_deadlock_detect = OFF, nobody breaks a deadlock for you: two transfers that wait for each
other wait until the server kills the transaction (8 s). When a transfer returns or raises, its
transaction ends and every lock it still holds is released (that is what a COMMIT or ROLLBACK does).
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from contextvars import ContextVar

from core.vtime import now

LOCK_LATENCY = 0.001  # a round trip to the lock manager
READ_LATENCY = 0.0015  # a round trip to read balances
COMMIT_LATENCY = 0.002  # a round trip to write them and commit
AUDIT = (0.002, 0.006)  # seconds an audit write takes per row, usually

# How a lock wait ended (the scenario keeps these for the pictures).
GOT, TIMED_OUT, KILLED = range(3)


class LockTimeout(Exception):
    """A lock wait took longer than its timeout. The transfer still holds the locks it got before."""


class Request:
    """The transfer being served (the scenario makes one per request; your code never sees it)."""

    __slots__ = ("rid", "tries", "wait", "timeouts", "audited_locked")

    def __init__(self, rid: int) -> None:
        self.rid = rid
        self.tries = 0  # times it started taking its locks from none held (1 + its retries)
        self.wait = 0.0  # seconds spent waiting for locks
        self.timeouts = 0  # lock waits that timed out
        self.audited_locked = 0  # audit writes made while holding a lock


current_request: ContextVar[Request | None] = ContextVar("current_request", default=None)


def _me() -> Request:
    req = current_request.get()
    if req is None:
        raise RuntimeError("no transfer is being served here")
    return req


class LockManager:
    """Exclusive locks on accounts, granted in arrival order.

    It also keeps, for the lab, who waits for whom (`waiting`, `holder`) so the scenario can find
    deadlocks, and calls `on_wait(t0, t1, rid, held, want, result)` when a wait ends.
    """

    def __init__(self, rng: random.Random | None = None, on_wait=None) -> None:
        self.rng = rng or random.Random(0)
        self.holder: dict[int, int] = {}  # account -> request id holding it
        self.queue: dict[int, deque] = {}  # account -> waiters: [rid, future, since, held]
        self.held: dict[int, list[int]] = {}  # request id -> accounts, in the order it got them
        self.waiting: dict[int, int] = {}  # request id -> the account it waits for
        self.on_wait = on_wait

    async def _half(self) -> None:
        await asyncio.sleep(LOCK_LATENCY / 2 * (0.8 + 0.4 * self.rng.random()))

    async def acquire(self, account: int, timeout: float | None = None) -> None:
        req = _me()
        rid = req.rid
        await self._half()
        held = self.held.setdefault(rid, [])
        if self.holder.get(account) == rid:  # already ours
            await self._half()
            return
        if not held:
            req.tries += 1
        if account not in self.holder:
            self.holder[account] = rid
            held.append(account)
        else:
            await self._wait(req, account, timeout, held[-1] if held else -1)
        await self._half()

    async def _wait(self, req: Request, account: int, timeout: float | None, last: int) -> None:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        since = now()
        entry = [req.rid, fut, since, last]
        self.queue.setdefault(account, deque()).append(entry)
        self.waiting[req.rid] = account
        handle = None
        if timeout is not None:
            handle = loop.call_later(max(0.0, float(timeout)), self._expire, fut)
        result = KILLED
        try:
            await fut
            result = GOT
        except LockTimeout:
            result = TIMED_OUT
            req.timeouts += 1
            raise
        finally:
            if handle is not None:
                handle.cancel()
            if self.waiting.get(req.rid) == account:
                del self.waiting[req.rid]
            if not fut.done() or result != GOT:
                q = self.queue.get(account)
                if q is not None and entry in q:
                    q.remove(entry)
            req.wait += now() - since
            if self.on_wait is not None:
                self.on_wait(since, now(), req.rid, last, account, result)

    @staticmethod
    def _expire(fut: asyncio.Future) -> None:
        if not fut.done():
            fut.set_exception(LockTimeout("lock wait timeout"))

    def release(self, account: int) -> None:
        """Release one lock this transfer holds (nothing happens if it does not hold it)."""
        self._release(_me().rid, account)

    def release_all(self) -> None:
        """Release every lock this transfer holds."""
        self.release_request(_me().rid)

    def holding(self) -> list[int]:
        return list(self.held.get(_me().rid, ()))

    # ---- inside the lock manager

    def release_request(self, rid: int) -> None:
        for account in list(self.held.get(rid, ())):
            self._release(rid, account)
        self.held.pop(rid, None)

    def _release(self, rid: int, account: int) -> None:
        if self.holder.get(account) != rid:
            return
        held = self.held.get(rid)
        if held is not None and account in held:
            held.remove(account)
        del self.holder[account]
        q = self.queue.get(account)
        while q:
            nxt, fut, _, _ = q.popleft()
            if fut.done():
                continue
            self.holder[account] = nxt
            self.held.setdefault(nxt, []).append(account)
            self.waiting.pop(nxt, None)
            fut.set_result(None)
            break
        if q is not None and not q:
            del self.queue[account]

    def cycles(self) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
        """Deadlocks right now: (request ids, accounts they wait for) of every cycle in the wait-for
        graph. Each waiter waits for one account, held by one transfer: follow the arrows."""
        out = []
        state: dict[int, int] = {}  # rid -> 1 on the current path, 2 done
        for start in self.waiting:
            if start in state:
                continue
            path = []
            rid = start
            while rid is not None and rid not in state:
                state[rid] = 1
                path.append(rid)
                acc = self.waiting.get(rid)
                rid = self.holder.get(acc) if acc is not None else None
                if rid is not None and rid not in self.waiting:
                    state[rid] = 2
                    rid = None
            if rid is not None and state.get(rid) == 1:
                ring = path[path.index(rid):]
                out.append((tuple(ring), tuple(self.waiting[r] for r in ring)))
            for r in path:
                state[r] = 2
        return out

    def held_by(self, rid: int) -> int:
        return len(self.held.get(rid, ()))


class Ledger:
    """Account balances, in cents. A move reads, then writes in one commit: correct only if nobody
    else wrote those accounts in between (the locks make sure of that).

    For the lab it keeps `drift`: the money that appeared or disappeared because a commit wrote
    over somebody else's update (0 when every writer held its locks).
    """

    def __init__(self, accounts, rng: random.Random | None = None, start: int = 1_000_000) -> None:
        self.rng = rng or random.Random(0)
        self.balances: dict[int, int] = {a: start for a in accounts}
        self.drift = 0
        self.slow = 1.0

    async def _trip(self, latency: float) -> None:
        await asyncio.sleep(latency * self.slow * (0.8 + 0.4 * self.rng.random()))

    async def move(self, src: int, dst: int, amount: int) -> None:
        await self.apply([(src, -amount), (dst, amount)])

    async def apply(self, entries) -> None:
        entries = [(int(a), int(d)) for a, d in entries]
        await self._trip(READ_LATENCY)
        read = {a: self.balances.get(a, 0) for a, _ in entries}
        await self._trip(COMMIT_LATENCY)
        new = dict(read)
        for a, d in entries:
            new[a] += d
        for a, value in new.items():  # the commit: one step
            self.drift += abs(self.balances.get(a, 0) - read[a])
            self.balances[a] = value

    def total(self) -> int:
        return sum(self.balances.values())


class Audit:
    """The audit log: an append-only store, one row per entry, usually quick. `slow` is the share of
    writes that stall for `stall` seconds (a disk stall, a failover)."""

    def __init__(self, locks: LockManager, rng: random.Random | None = None) -> None:
        self.locks = locks
        self.rng = rng or random.Random(0)
        self.slow = 0.0
        self.stall = (0.2, 0.6)
        self.busy = 1.0  # every write takes this many times longer (the log is busy)
        self.records = 0
        self.locked = 0  # writes made while holding a lock

    async def record(self, entries) -> None:
        req = current_request.get()
        if req is not None and self.locks.held_by(req.rid):
            req.audited_locked += 1
            self.locked += 1
        if self.slow and self.rng.random() < self.slow:
            await asyncio.sleep(self.rng.uniform(*self.stall))
        else:
            await asyncio.sleep(self.rng.uniform(*AUDIT) * self.busy * max(1, len(entries)))
        self.records += 1
