"""Lab deadlock_avoidance: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
import random

from labs.deadlock_avoidance.api import LockTimeout

LOCK_TIMEOUT = 2.0  # a safety net: with one lock order nothing waits this long unless something broke
MAX_TRIES = 3  # tries per transfer, the first one included
BASE = 0.01  # seconds; the largest wait after the first timeout
CAP = 0.2  # seconds; no wait is ever longer than this


def backoff(attempt: int, rng: random.Random) -> float:
    # Full jitter: two transfers that timed out against each other come back at different moments.
    return rng.uniform(0, min(CAP, BASE * 2 ** min(attempt, 30)))


def lock_order(accounts) -> list[int]:
    # One global order for every lock anybody takes: a cycle would need somebody to wait for a
    # smaller id while holding a bigger one, and nobody does.
    return sorted(set(accounts))


class Payments:
    def __init__(self, locks, ledger, audit, rng: random.Random | None = None) -> None:
        self.locks = locks
        self.ledger = ledger
        self.audit = audit
        self.rng = rng or random.Random(0)

    async def lock_all(self, accounts) -> None:
        for attempt in range(1, MAX_TRIES + 1):
            try:
                for account in accounts:
                    await self.locks.acquire(account, timeout=LOCK_TIMEOUT)
                return
            except LockTimeout:
                self.locks.release_all()  # never wait (or back off) while holding a lock
                if attempt == MAX_TRIES:
                    raise
                await asyncio.sleep(backoff(attempt, self.rng))

    async def transfer(self, src: int, dst: int, amount: int) -> None:
        await self.lock_all(lock_order([src, dst]))
        try:
            await self.ledger.move(src, dst, amount)  # the critical section: only the ledger
        finally:
            self.locks.release_all()
        await self.audit.record([(src, -amount), (dst, amount)])  # slow work, after the locks

    async def settle(self, entries) -> None:
        await self.lock_all(lock_order(account for account, _ in entries))  # all of them, up front
        try:
            await self.ledger.apply(entries)
        finally:
            self.locks.release_all()
        await self.audit.record(entries)
