"""Lab deadlock_avoidance: YOUR FILE. Edit it and save; the live window reruns it.

A payments service moves money between accounts. Every transfer locks both accounts (row locks in
the ledger), moves the money, writes the audit log and releases the locks. Right now it locks in
request order: first `src`, then `dst`. When A pays B while B pays A, each holds one lock and waits
for the other, forever: a deadlock. Then every transfer that touches A or B waits behind them,
holding its own first lock, and the pile grows until the service has no workers left and freezes.
Nobody breaks it until the server kills the transactions (8 s later).

Do the stages in order, in this file:

  Stage 1  Lock timeouts with retry: in `lock_all`, acquire with `timeout=LOCK_TIMEOUT` (0.05 s).
           On LockTimeout, `release_all()` (never wait while holding a lock), sleep
           `backoff(attempt, rng)`, and try again, up to MAX_TRIES (8) tries; after the last, raise.
           No more freezes, but every deadlock (and every long wait at a busy account) now costs
           timeouts, retries and latency. Without jitter, two transfers that collided retry in step
           and collide again (a livelock).
  Stage 2  One global lock order: in `lock_order`, sort the accounts by id and lock them in that
           order, in `transfer` and in `settle` (the batch job: all its accounts, in order, before
           it moves anything). A cycle needs somebody to wait for a smaller id while holding a
           bigger one: nobody does, so there are no deadlocks at all. Keep a long LOCK_TIMEOUT
           (2 s) and MAX_TRIES = 3 only as a safety net, and keep the critical section short: write
           the audit log AFTER releasing the locks, so a slow audit write holds nobody up.

What you get (see labs/deadlock_avoidance/api.py):
  await self.locks.acquire(account, timeout=None)   raises LockTimeout after `timeout` seconds
  self.locks.release(account)    self.locks.release_all()    self.locks.holding()
  await self.ledger.move(src, dst, amount)          await self.ledger.apply(entries)
  await self.audit.record(entries)                  2-6 ms a row; sometimes it stalls
  self.rng (a random.Random) for the jitter

When transfer() or settle() returns or raises, its transaction ends: every lock it holds is
released. Raise LockTimeout to give up (the client gets an error).

Check yourself:  uv run pytest labs/deadlock_avoidance
Peek at a solution (after trying!):  labs/deadlock_avoidance/reference.py
"""

from __future__ import annotations

import asyncio
import random

from labs.deadlock_avoidance.api import LockTimeout

LOCK_TIMEOUT = None  # seconds a lock wait may last; None waits forever. Stage 1: 0.05. Stage 2: 2.0
MAX_TRIES = 1  # tries per transfer, the first one included. Stage 1: 8. Stage 2: 3
BASE = 0.01  # stage 1: seconds; the largest wait after the first timeout
CAP = 0.2  # stage 1: seconds; no wait is ever longer than this


def backoff(attempt: int, rng: random.Random) -> float:
    """Stage 1. Seconds to wait after timeout number `attempt` (1 after the first one).

    Contract:
      - A random wait between 0 and min(CAP, BASE * 2 ** attempt) ("full jitter").
      - Never negative, never above CAP, however large `attempt` is.
      - Use `rng` (not the `random` module), so a run is the same every time.
    """
    # Stage 1: return rng.uniform(0, min(CAP, BASE * 2 ** min(attempt, 30)))
    raise NotImplementedError("TODO stage 1: backoff(attempt, rng)")


def lock_order(accounts) -> list[int]:
    """Stage 2. The order to lock `accounts` in: the same for every transfer and every batch.

    Contract:
      - Every account once, in ascending id order: lock_order([9, 4, 9, 2]) == [2, 4, 9].
      - Takes any iterable (a list, a generator).
    """
    # Stage 2: return sorted(set(accounts))
    raise NotImplementedError("TODO stage 2: lock_order(accounts)")


class Payments:
    """Moves money between accounts without deadlocks, lost money or a frozen service.

    Contract:
      - `await transfer(src, dst, amount)` moves `amount` cents from `src` to `dst`, holding both
        accounts' locks while it calls the ledger. Raise LockTimeout to give up.
      - `await settle(entries)` applies a batch, [(account, delta)] (the deltas add up to 0),
        holding every account's lock while it calls the ledger.
      - Release your locks when you are done (or when you give up a try).
    """

    def __init__(self, locks, ledger, audit, rng: random.Random | None = None) -> None:
        self.locks = locks
        self.ledger = ledger
        self.audit = audit
        self.rng = rng or random.Random(0)

    async def lock_all(self, accounts) -> None:
        # Stage 1: put this in a loop of MAX_TRIES tries. On LockTimeout: self.locks.release_all(),
        #          and if that was the last try, raise; else
        #          `await asyncio.sleep(backoff(attempt, self.rng))` and start again from the first.
        for account in accounts:
            await self.locks.acquire(account, timeout=LOCK_TIMEOUT)  # waits forever if None

    async def transfer(self, src: int, dst: int, amount: int) -> None:
        # Stage 2: lock `lock_order([src, dst])`, and move the audit write after the finally.
        await self.lock_all([src, dst])  # src first: B -> A takes B first while A -> B holds A
        try:
            await self.ledger.move(src, dst, amount)
            await self.audit.record([(src, -amount), (dst, amount)])  # slow work, holding both locks
        finally:
            self.locks.release_all()

    async def settle(self, entries) -> None:
        # Stage 2: lock `lock_order(account for account, _ in entries)`, and audit after the finally.
        await self.lock_all([account for account, _ in entries])  # in the job's order
        try:
            await self.ledger.apply(entries)
            await self.audit.record(entries)
        finally:
            self.locks.release_all()

