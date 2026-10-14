"""What your Orchestrator gets: three services, each with a step and its compensation, and a log.

    await payments.charge(order, key=None) -> ref     takes the money   (Declined: card declined)
    await payments.refund(ref=None, key=None)         gives it back
    await stock.reserve(order, key=None) -> ref       holds the items   (Declined: out of stock)
    await stock.release(ref=None, key=None)           puts them back
    await shipping.book(order, key=None) -> ref       books a courier   (Declined: the carrier refused)
    await shipping.cancel(ref=None, key=None)         cancels it

A call takes 15-60 ms and can raise:
    Declined   a definite no: nothing happened. Retrying will not help; roll back.
    Timeout    no answer within 0.5 s: it may have happened, or not. You cannot tell.
Both are StepFailed.

With `key=...` a step is idempotent: the same key again returns the first ref and does nothing new
(even if it was undone since). Without a key every call is a new charge, reservation or booking.
A compensation undoes the step with that ref, or the step made with that key; undoing twice, or
undoing what never happened, does nothing. Compensations never say Declined, but they can time
out: retry them.

    await log.save(saga_id, state)    durable: it survives a crash (each call ~2 ms)
    await log.delete(saga_id)
    await log.items() -> [(saga_id, state)]   what the log held when you called it

Everything else on your Orchestrator lives in memory, and a crash loses it.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import random
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from core.vtime import now

TIMEOUT = 0.5  # seconds before a call gives up waiting for its answer
APPLIED = 0.5  # share of timed-out calls that did happen (the answer was lost, not the request)

# What a call did, as the service saw it.
OK, DECLINED, TIMEOUT_LOST, TIMEOUT_DONE = range(4)


class StepFailed(Exception):
    """A step or a compensation did not answer OK."""


class Declined(StepFailed):
    """A definite no (card declined, out of stock, the carrier refused): nothing happened."""


class Timeout(StepFailed):
    """No answer in time: the call may have happened, or not."""


class Crashed(BaseException):
    """This orchestrator is dead (it crashed): its calls go nowhere. Not an Exception on purpose."""


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    account: int
    amount: int  # cents
    items: int
    address: str


# Which orchestrator a call comes from: the scenario sets it; calls from a dead one raise Crashed.
epoch: ContextVar[int | None] = ContextVar("orchestrator_epoch", default=None)
# The order a saga's calls belong to (set by the scenario while place() runs).
current_order: ContextVar[int | None] = ContextVar("current_order", default=None)


class Plant:
    """The scenario's switch: which orchestrator is alive."""

    def __init__(self) -> None:
        self.epoch = 0

    def check(self) -> None:
        e = epoch.get()
        if e is not None and e != self.epoch:
            raise Crashed()


def _detached(coro) -> asyncio.Task:
    """The service's side of a call: it runs to the end even if the caller is gone."""
    task = asyncio.ensure_future(coro)
    task.add_done_callback(lambda t: t.cancelled() or t.exception())  # nobody may be listening
    return task


@dataclass(slots=True)
class Op:
    order: int
    ref: str
    held: bool = True  # not undone (yet)
    answered: bool = False  # the orchestrator got its ref back


class Service:
    """One service: a step that does something for an order, and the compensation that undoes it."""

    def __init__(self, name: str, index: int, latency: float, rng: random.Random | None = None,
                 plant: Plant | None = None,
                 on_call: Callable[[float, int, int, bool, float, int], None] | None = None) -> None:
        self.name = name
        self.index = index
        self.latency = latency
        self.rng = rng or random.Random(index)
        self.plant = plant
        self.on_call = on_call
        self.timeout_share = 0.0  # share of calls that time out (an incident sets it)
        self.refuse: Callable[[Order], bool] = lambda order: False  # does the step say no?
        self.ops: dict[str, Op] = {}
        self.keys: dict[str, str] = {}  # key -> ref
        self.key_order: dict[str, int] = {}  # key -> order (also for steps that never happened)
        self.by_order: dict[int, list[Op]] = {}
        self.order_keys: dict[int, list[str]] = {}
        self._ids = itertools.count(1)

    # ---- what the scenario reads

    def held(self, order: int) -> int:
        return sum(1 for op in self.by_order.get(order, ()) if op.held)

    def made(self, order: int) -> int:
        return len(self.by_order.get(order, ()))

    def known_held(self, order: int) -> bool:
        """Something the orchestrator was told happened is still held."""
        return any(op.held and op.answered for op in self.by_order.get(order, ()))

    def forget(self, order: int) -> None:
        for op in self.by_order.pop(order, ()):
            self.ops.pop(op.ref, None)
        for key in self.order_keys.pop(order, ()):
            self.keys.pop(key, None)
            self.key_order.pop(key, None)

    # ---- calls

    def _record(self, start: float, order: int, undo: bool, outcome: int) -> None:
        if self.on_call is not None:
            self.on_call(start, order, self.index, undo, now(), outcome)

    def _remember_key(self, key: str, order: int) -> None:
        if key not in self.key_order:
            self.key_order[key] = order
            self.order_keys.setdefault(order, []).append(key)

    def _wait(self) -> float:
        return self.latency * (0.6 + 0.8 * self.rng.random())

    async def step(self, order: Order, key: str | None = None) -> str:
        if self.plant is not None:
            self.plant.check()
        if key is not None:
            self._remember_key(key, order.id)
        # The work runs on its own: if the orchestrator dies while waiting, the service still does it.
        op = await asyncio.shield(_detached(self._step(order, key)))
        op.answered = True
        return op.ref

    async def _step(self, order: Order, key: str | None) -> Op:
        start = now()
        timeout = self.timeout_share > 0 and self.rng.random() < self.timeout_share
        applied = timeout and self.rng.random() < APPLIED
        if timeout and not applied:  # the request was lost: nothing happens, nobody answers
            await asyncio.sleep(TIMEOUT)
            self._record(start, order.id, False, TIMEOUT_LOST)
            raise Timeout(f"{self.name}: no answer")
        await asyncio.sleep(self._wait())
        ref = self.keys.get(key) if key is not None else None
        op = self.ops.get(ref) if ref is not None else None
        if op is None:  # new work (a known key just gets its first answer again)
            if self.refuse(order):
                self._record(start, order.id, False, DECLINED)
                raise Declined(f"{self.name}: declined")
            op = Op(order.id, f"{self.name[:3]}-{next(self._ids)}")
            self.ops[op.ref] = op
            self.by_order.setdefault(order.id, []).append(op)
            if key is not None:
                self.keys[key] = op.ref
        if applied:  # done, but the answer is lost on the way back
            await asyncio.sleep(max(0.0, TIMEOUT - (now() - start)))
            self._record(start, order.id, False, TIMEOUT_DONE)
            raise Timeout(f"{self.name}: no answer")
        self._record(start, order.id, False, OK)
        return op

    async def undo(self, ref: str | None = None, key: str | None = None) -> None:
        if self.plant is not None:
            self.plant.check()
        await asyncio.shield(_detached(self._undo(ref, key)))

    async def _undo(self, ref: str | None, key: str | None) -> None:
        start = now()
        if ref is None and key is not None:
            ref = self.keys.get(key)
        op = self.ops.get(ref) if ref is not None else None
        if op is not None:
            order = op.order
        elif key is not None and key in self.key_order:
            order = self.key_order[key]
        else:  # undoing what never happened: whose saga is it?
            order = current_order.get()
            order = -1 if order is None else order
        timeout = self.timeout_share > 0 and self.rng.random() < self.timeout_share
        applied = timeout and self.rng.random() < APPLIED
        if timeout and not applied:
            await asyncio.sleep(TIMEOUT)
            self._record(start, order, True, TIMEOUT_LOST)
            raise Timeout(f"{self.name}: no answer")
        await asyncio.sleep(self._wait())
        if op is not None:
            op.held = False
        if applied:
            await asyncio.sleep(max(0.0, TIMEOUT - (now() - start)))
            self._record(start, order, True, TIMEOUT_DONE)
            raise Timeout(f"{self.name}: no answer")
        self._record(start, order, True, OK)


class Payments(Service):
    async def charge(self, order: Order, key: str | None = None) -> str:
        """Take the money. Raises Declined (card declined) or Timeout."""
        return await self.step(order, key)

    async def refund(self, ref: str | None = None, key: str | None = None) -> None:
        """Give back the charge with this ref, or the one made with this key."""
        await self.undo(ref, key)


class Stock(Service):
    async def reserve(self, order: Order, key: str | None = None) -> str:
        """Hold the items. Raises Declined (out of stock) or Timeout."""
        return await self.step(order, key)

    async def release(self, ref: str | None = None, key: str | None = None) -> None:
        """Put back the reservation with this ref, or the one made with this key."""
        await self.undo(ref, key)


class Shipping(Service):
    async def book(self, order: Order, key: str | None = None) -> str:
        """Book a courier. Raises Declined (the carrier refused) or Timeout."""
        return await self.step(order, key)

    async def cancel(self, ref: str | None = None, key: str | None = None) -> None:
        """Cancel the booking with this ref, or the one made with this key."""
        await self.undo(ref, key)


class SagaLog:
    """Durable storage for saga state: it survives a crash of the orchestrator. Each call ~2 ms."""

    def __init__(self, latency: float = 0.002, plant: Plant | None = None) -> None:
        self.latency = latency
        self.plant = plant
        self._data: dict[str, Any] = {}

    def __len__(self) -> int:
        return len(self._data)

    def _check(self) -> None:
        if self.plant is not None:
            self.plant.check()

    async def save(self, saga_id: str, state: Any) -> None:
        self._check()
        state = copy.deepcopy(state)
        await asyncio.sleep(self.latency)
        self._check()
        self._data[saga_id] = state

    async def delete(self, saga_id: str) -> None:
        self._check()
        await asyncio.sleep(self.latency)
        self._check()
        self._data.pop(saga_id, None)

    async def items(self) -> list[tuple[str, Any]]:
        self._check()
        snapshot = [(k, copy.deepcopy(v)) for k, v in self._data.items()]
        await asyncio.sleep(self.latency)
        return snapshot


def services(seed: int = 0, plant: Plant | None = None, on_call=None) -> tuple[Payments, Stock, Shipping]:
    """The three services with their usual speeds."""
    return (Payments("payments", 0, 0.040, random.Random(seed * 3 + 1), plant, on_call),
            Stock("stock", 1, 0.015, random.Random(seed * 3 + 2), plant, on_call),
            Shipping("shipping", 2, 0.060, random.Random(seed * 3 + 3), plant, on_call))
