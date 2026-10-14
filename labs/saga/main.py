"""Lab saga: YOUR FILE. Edit it and save; the live window reruns it.

An order spans three services, and there is no transaction across them. Your `Orchestrator`
runs one saga per order: charge the card (payments), reserve the items (stock), book a
courier (shipping). Right now it just calls them in order: when a step fails half way, the
steps before it stay done. The customer is charged for an order that never ships, and the
items stay reserved for nobody.

Do the stages in order, in this file:

  Stage 1  Compensate: when a step fails, undo the steps that succeeded, last first
           (release the stock, then refund the card), and return False.
  Stage 2  Idempotent, resumable sagas. A step can time out and still have happened, and
           the orchestrator itself can crash half way (a deploy, an OOM kill).
           - Pass key=saga_id to every step and compensation: a retry then never charges
             twice, and you can undo a step whose answer you never got.
           - Retry timeouts with backoff (`attempt`); keep retrying compensations.
           - Save the saga's state in `self.log` before each phase ("running", then
             "compensating"), delete it when the saga ends, and in `recover()` finish every
             saga the log still has.

What you get (see labs/saga/api.py):
  await payments.charge(order, key=None) -> ref      await payments.refund(ref=None, key=None)
  await stock.reserve(order, key=None) -> ref        await stock.release(ref=None, key=None)
  await shipping.book(order, key=None) -> ref        await shipping.cancel(ref=None, key=None)
  Declined (a definite no), Timeout (no answer: it may have happened); both are StepFailed
  await log.save(saga_id, state) / log.delete(saga_id) / log.items() -> [(saga_id, state)]

Check yourself:  uv run pytest labs/saga
Peek at a solution (after trying!):  labs/saga/reference.py
"""

from __future__ import annotations

import asyncio

from labs.saga.api import StepFailed, Timeout

TRIES = 6  # tries of a step that times out, with the same key, before giving up on it
UNDO_TRIES = 40  # a compensation must happen: keep trying (backoff capped at MAX_BACKOFF)
BACKOFF = 0.1  # seconds before the first retry; doubles each time
MAX_BACKOFF = 1.0


class Orchestrator:
    """Runs the saga of each order: charge -> reserve -> book.

    Contract:
      - `await orch.place(saga_id, order)` runs a new saga. Return True when the order is
        complete (charged, reserved, booked) and False when you rolled it back. If it raises
        StepFailed, you gave up and left everything as it was.
      - `await orch.recover()` is called once on a NEW orchestrator after a crash (the same
        services and log; everything you kept in memory is gone). Finish every saga the crash
        interrupted, forward or backward.
      - Never catch other exceptions: they are bugs and must surface.
    """

    def __init__(self, payments, stock, shipping, log) -> None:
        self.payments = payments
        self.stock = stock
        self.shipping = shipping
        self.log = log
        # Each step with its compensation, in order.
        self.steps = [(payments.charge, payments.refund), (stock.reserve, stock.release),
                      (shipping.book, shipping.cancel)]

    async def place(self, saga_id: str, order) -> bool:
        # Stage 1: keep the refs the steps return in a list; wrap the steps in
        #          `try: ... except StepFailed:` and there `await self.compensate(saga_id, refs)`
        #          and return False.
        # Stage 2: first `await self.log.save(saga_id, {"order": order, "status": "running"})`,
        #          then `return await self.resume(saga_id, that state)`, and move the steps there.
        await self.payments.charge(order)
        await self.stock.reserve(order)
        await self.shipping.book(order)
        return True

    async def recover(self) -> None:
        # Stage 2: `for saga_id, state in await self.log.items():` resume each one, all at once
        #          (`asyncio.gather(..., return_exceptions=True)`).
        return  # nothing was saved, so there is nothing to resume

    async def resume(self, saga_id: str, state: dict) -> bool:
        """Stage 2. Run a saga from its saved state, and delete it from the log when it ends.

          status "running":       run every step with `self.attempt(do, order, key=saga_id)`; a
                                  step that already happened just returns its first ref. If one
                                  fails for good, save status "compensating", then compensate.
          status "compensating":  compensate (a crash came while undoing: undo it all again).
        Return True if the order completed, False if it was rolled back.
        """
        raise NotImplementedError("TODO stage 2: Orchestrator.resume")

    async def compensate(self, saga_id: str, refs: list) -> None:
        """Stage 1. Undo the steps that happened, last first.

        `refs[i]` is what step i returned. Stage 1: `await undo(ref)` for each ref you got,
        in reverse order (zip `self.steps` with `refs`, then `reversed`).
        Stage 2: undo every step by key, `await self.attempt(undo, None, key=saga_id,
        tries=UNDO_TRIES)`, even the one that timed out: it may have happened, and undoing
        what never happened does nothing.
        """
        raise NotImplementedError("TODO stage 1: Orchestrator.compensate")

    async def attempt(self, call, *args, tries: int = TRIES, **kwargs):
        """Stage 2. `await call(*args, **kwargs)`; on Timeout, sleep
        min(MAX_BACKOFF, BACKOFF * 2 ** n) and try again, up to `tries` times, then raise.
        Retrying is only safe because the call carries a key. Let Declined through at once."""
        raise NotImplementedError("TODO stage 2: Orchestrator.attempt")
