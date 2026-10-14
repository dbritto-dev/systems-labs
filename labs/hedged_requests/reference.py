"""Lab hedged_requests: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
import random

HEDGE_AFTER = 0.020


class Client:
    def __init__(self, replicas: list, rng: random.Random | None = None) -> None:
        self.replicas = replicas
        self.rng = rng or random.Random(0)
        self.budget = HedgeBudget()

    async def read(self, key):
        self.budget.deposit()
        first, second = self.rng.sample(self.replicas, 2)
        calls = [asyncio.ensure_future(first.get(key))]
        try:
            done, _ = await asyncio.wait(calls, timeout=HEDGE_AFTER)
            # Slow so far: send a copy, if the budget allows one.
            if not done and self.budget.try_withdraw():
                calls.append(asyncio.ensure_future(second.get(key)))
            done, _ = await asyncio.wait(calls, return_when=asyncio.FIRST_COMPLETED)
            return done.pop().result()
        finally:
            # The loser (or both, if the user gave up): nobody needs its answer.
            for call in calls:
                call.cancel()


class HedgeBudget:
    def __init__(self, ratio: float = 0.05, max_tokens: float = 10) -> None:
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
