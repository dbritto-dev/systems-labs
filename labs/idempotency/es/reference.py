"""Laboratorio idempotency: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio

from labs.idempotency.api import IN_PROGRESS, Conflict

TTL = 300.0  # segundos que se recuerda una clave
WAIT_STEP = 0.05  # cada cuánto un duplicado mira si el primer intento ya terminó
WAIT_STEPS = 40  # ... durante hasta 2 s; después responde 409


class PaymentService:
    def __init__(self, ledger, store) -> None:
        self.ledger = ledger
        self.store = store

    async def charge(self, key: str, account: int, amount: int) -> dict:
        # Reclama la clave en un solo paso: solo un intento de un pago puede ganar, por muy
        # juntos que lleguen.
        if await self.store.add(key, IN_PROGRESS, TTL):
            receipt = {"charge_id": await self.ledger.insert(account, amount), "amount": amount}
            await self.store.set(key, receipt, TTL)
            return receipt
        # Otro la tiene: espera su recibo y responde con él.
        for _ in range(WAIT_STEPS):
            seen = await self.store.get(key)
            if isinstance(seen, dict):
                return seen
            await asyncio.sleep(WAIT_STEP)
        raise Conflict(key)
