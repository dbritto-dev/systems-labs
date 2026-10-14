"""Lab idempotency: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio

from labs.idempotency.api import IN_PROGRESS, Conflict

TTL = 300.0  # seconds a key is remembered
WAIT_STEP = 0.05  # how often a duplicate checks whether the first try has finished
WAIT_STEPS = 40  # ... for up to 2 s, then it answers 409


class PaymentService:
    def __init__(self, ledger, store) -> None:
        self.ledger = ledger
        self.store = store

    async def charge(self, key: str, account: int, amount: int) -> dict:
        # Claim the key in one step: only one try of a payment can win, however close they arrive.
        if await self.store.add(key, IN_PROGRESS, TTL):
            receipt = {"charge_id": await self.ledger.insert(account, amount), "amount": amount}
            await self.store.set(key, receipt, TTL)
            return receipt
        # Someone has it: wait for their receipt, and answer with it.
        for _ in range(WAIT_STEPS):
            seen = await self.store.get(key)
            if isinstance(seen, dict):
                return seen
            await asyncio.sleep(WAIT_STEP)
        raise Conflict(key)
