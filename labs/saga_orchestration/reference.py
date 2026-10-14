"""Lab saga_orchestration: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio

from labs.saga_orchestration.api import StepFailed, Timeout

TRIES = 6  # tries of a step that times out, with the same key, before giving up on it
UNDO_TRIES = 40  # a compensation must happen: keep trying (backoff capped at MAX_BACKOFF)
BACKOFF = 0.1  # seconds before the first retry; doubles each time
MAX_BACKOFF = 1.0


class Orchestrator:
    def __init__(self, payments, stock, shipping, log) -> None:
        self.payments = payments
        self.stock = stock
        self.shipping = shipping
        self.log = log
        # Each step with its compensation, in order.
        self.steps = [(payments.charge, payments.refund), (stock.reserve, stock.release),
                      (shipping.book, shipping.cancel)]

    async def place(self, saga_id: str, order) -> bool:
        # Write ahead: the log knows about the saga before the first step can happen.
        state = {"order": order, "status": "running"}
        await self.log.save(saga_id, state)
        return await self.resume(saga_id, state)

    async def recover(self) -> None:
        # A new orchestrator after a crash: finish every saga the log says is unfinished.
        sagas = await self.log.items()
        await asyncio.gather(*(self.resume(saga_id, state) for saga_id, state in sagas),
                             return_exceptions=True)

    async def resume(self, saga_id: str, state: dict) -> bool:
        """Run a saga from its saved state: forward while it is running, else compensate."""
        order = state["order"]
        if state["status"] == "running":
            refs = []
            try:
                for do, _ in self.steps:
                    # The same key every time: a step that already happened returns its first ref.
                    refs.append(await self.attempt(do, order, key=saga_id))
                await self.log.delete(saga_id)
                return True
            except StepFailed:
                pass  # declined, or no answer after every try: roll back
            # Say so before undoing anything, so a crash from here on keeps compensating.
            await self.log.save(saga_id, {"order": order, "status": "compensating"})
        await self.compensate(saga_id, [None] * len(self.steps))
        await self.log.delete(saga_id)
        return False

    async def compensate(self, saga_id: str, refs: list) -> None:
        """Undo the steps, last first, by key: undoing what never happened does nothing, so a step
        that timed out (and maybe happened) is undone too."""
        for (_, undo), ref in reversed(list(zip(self.steps, refs))):
            await self.attempt(undo, ref, key=saga_id, tries=UNDO_TRIES)

    async def attempt(self, call, *args, tries: int = TRIES, **kwargs):
        """Call a step or a compensation, retrying timeouts with backoff (safe: it carries a key)."""
        for n in range(tries):
            try:
                return await call(*args, **kwargs)
            except Timeout:
                if n == tries - 1:
                    raise
                await asyncio.sleep(min(MAX_BACKOFF, BACKOFF * 2 ** n))
