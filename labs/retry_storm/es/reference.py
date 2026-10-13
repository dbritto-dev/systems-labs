"""Laboratorio retry_storm: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
import random

from core.services import ServiceError

MAX_RETRIES = 3


class Client:
    def __init__(self, service, rng: random.Random | None = None) -> None:
        self.service = service
        self.rng = rng or random.Random(0)
        self.budget = RetryBudget()

    async def call(self, payload=None):
        self.budget.deposit()
        attempt = 0
        while True:
            try:
                return await self.service.call(payload)
            except ServiceError:
                attempt += 1
                # Primero el número de reintentos, para no gastar nunca un token en
                # un reintento que de todas formas no haríamos.
                if attempt > MAX_RETRIES or not self.budget.try_withdraw():
                    raise
                await asyncio.sleep(backoff_delay(attempt, rng=self.rng))


def backoff_delay(attempt: int, base: float = 0.1, cap: float = 5.0,
                  rng: random.Random | None = None) -> float:
    r = rng or random
    return r.uniform(0, min(cap, base * 2 ** min(attempt, 32)))


class RetryBudget:
    def __init__(self, ratio: float = 0.1, max_tokens: float = 10) -> None:
        self.ratio = ratio
        self.max_tokens = max_tokens
        self.tokens = float(max_tokens)

    def deposit(self) -> None:
        self.tokens = min(self.max_tokens, self.tokens + self.ratio)

    def try_withdraw(self) -> bool:
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True
