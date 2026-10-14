"""Lab idempotency: YOUR FILE. Edit it and save; the live window reruns it.

Clients pay through `PaymentService.charge(key, account, amount)`. Each payment carries an
idempotency key. When an answer gets lost or is slow, the client retries with the SAME key.
Right now every try charges the card again: a retried payment is charged twice.

Do the stages in order, in this file:

  Stage 1  Remember answers: after charging, store the receipt under the key; when the key
           comes again, return the stored receipt instead of charging.
  Stage 2  Reserve the key first: a retry can arrive while the first try is still charging.
           Claim the key atomically (`store.add`, like Redis SET NX) before charging; a
           duplicate that finds it in progress waits for the receipt (or raises Conflict).
           Store everything with an expiry (ttl) so the store does not grow forever.

What you get (see labs/idempotency/api.py):
  await self.ledger.insert(account, amount) -> charge_id     every call is a new charge
  await self.store.get(key) / .set(key, value, ttl) / .add(key, value, ttl) -> bool
  IN_PROGRESS, Conflict

Check yourself:  uv run pytest labs/idempotency
Peek at a solution (after trying!):  labs/idempotency/reference.py
"""

from __future__ import annotations

import asyncio

from labs.idempotency.api import IN_PROGRESS, Conflict

TTL = 300.0  # seconds a key is remembered


class PaymentService:
    """Charges a card once per idempotency key.

    Contract:
      - `await service.charge(key, account, amount)` returns a receipt:
        {"charge_id": <int>, "amount": <amount>}.
      - The same key must never be charged twice, and every try of the same key should get
        the same receipt.
      - Raise `Conflict(key)` if you cannot answer yet (the client retries a bit later).
    """

    def __init__(self, ledger, store) -> None:
        self.ledger = ledger
        self.store = store

    async def charge(self, key: str, account: int, amount: int) -> dict:
        # Stage 1: first `seen = await self.store.get(key)`; if there is a receipt, return it.
        #          After charging, `await self.store.set(key, receipt, TTL)`.
        # Stage 2: claim the key before charging: `if await self.store.add(key, IN_PROGRESS, TTL):`
        #          charge and store the receipt; otherwise wait (poll `get` every ~50 ms, up to
        #          ~2 s) until the value is a receipt, and raise Conflict(key) if it never is.
        charge_id = await self.ledger.insert(account, amount)
        return {"charge_id": charge_id, "amount": amount}


