"""What your Consumer gets: a queue like Amazon SQS, its dead-letter queue, and the job to run.

    msg.id, msg.body             one delivery of a message
    msg.receive_count            how many times it has been delivered: 1 the first time
    await queue.delete(msg)      ack: the job is done, remove the message for good -> bool
    await queue.change_visibility(msg, seconds)
                                 hide it until `seconds` from now -> bool. While a worker holds
                                 a message it is invisible; when its visibility timeout runs
                                 out, the queue hands it to another worker.
    await dlq.send(msg)          park it in the dead-letter queue (then delete it from the queue)
    await handle(msg)            do the job: raises JobFailed when it fails

`delete` and `change_visibility` return False when the message is gone, or has been delivered
again since this delivery (another worker holds it now): stop working on it.

Every call to the queue takes ~2 ms. A worker process that crashes stops at once: its calls
never return, and the messages it held become visible again when their timeout runs out.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from core.vtime import now

VISIBILITY = 2.0  # seconds a received message stays invisible, unless you change it
LONG_POLL = 1.0  # seconds receive() waits for a message before returning None
NET = 0.002  # one call to the queue


class JobFailed(Exception):
    """The job could not be done this time (a downstream error, a bad payload, a timeout)."""


@dataclass(frozen=True, slots=True)
class Message:
    """One delivery of a message. Each delivery has its own receipt: only the latest one counts."""

    id: int
    body: dict
    receive_count: int
    receipt: int
    sent_at: float


class _Record:
    __slots__ = ("id", "body", "sent_at", "visible_at", "receipt", "receives")

    def __init__(self, mid: int, body: dict, sent_at: float) -> None:
        self.id, self.body, self.sent_at = mid, body, sent_at
        self.visible_at = sent_at
        self.receipt = 0
        self.receives = 0


class Broker:
    """The queue itself (shared by every worker). Messages are handed out roughly oldest first."""

    def __init__(self, visibility: float = VISIBILITY,
                 on_receive: Callable[[_Record], None] | None = None,
                 on_gone: Callable[[int], None] | None = None) -> None:
        self.visibility = visibility
        self.on_receive = on_receive
        self.on_gone = on_gone
        self.records: dict[int, _Record] = {}
        self._ready: list[tuple[float, int]] = []  # (visible at, id); stale entries are skipped
        self._waiters: deque[asyncio.Future] = deque()
        self._ids = itertools.count()

    # ---- producers

    def send(self, body: dict) -> int:
        rec = _Record(next(self._ids), body, now())
        self.records[rec.id] = rec
        heapq.heappush(self._ready, (rec.visible_at, rec.id))
        self._wake()
        return rec.id

    # ---- what the queue does

    def _wake(self) -> None:
        while self._waiters:
            f = self._waiters.popleft()
            if not f.done():
                f.set_result(None)
                return

    def _hide(self, rec: _Record, seconds: float) -> None:
        rec.visible_at = now() + max(0.0, seconds)
        heapq.heappush(self._ready, (rec.visible_at, rec.id))
        if seconds <= 0:
            self._wake()
        else:
            asyncio.get_running_loop().call_at(rec.visible_at, self._wake)

    def _pop(self) -> _Record | None:
        t = now()
        while self._ready:
            at, mid = self._ready[0]
            rec = self.records.get(mid)
            if rec is None or rec.visible_at != at:
                heapq.heappop(self._ready)  # deleted, or hidden again since
                continue
            if at > t + 1e-9:
                return None
            heapq.heappop(self._ready)
            return rec
        return None

    def _current(self, msg: Message) -> _Record | None:
        rec = self.records.get(msg.id)
        return rec if rec is not None and rec.receipt == msg.receipt else None

    async def receive(self, wait: float = LONG_POLL) -> Message | None:
        await asyncio.sleep(NET)
        loop = asyncio.get_running_loop()
        deadline = now() + wait
        while True:
            rec = self._pop()
            if rec is not None:
                rec.receives += 1
                rec.receipt += 1
                self._hide(rec, self.visibility)
                if self.on_receive is not None:
                    self.on_receive(rec)
                return Message(rec.id, rec.body, rec.receives, rec.receipt, rec.sent_at)
            if now() >= deadline:
                return None
            fut = loop.create_future()
            self._waiters.append(fut)
            timer = loop.call_at(deadline, lambda f=fut: f.done() or f.set_result(None))
            try:
                await fut
            finally:
                timer.cancel()

    async def delete(self, msg: Message) -> bool:
        await asyncio.sleep(NET)
        rec = self._current(msg)
        if rec is None:
            return False
        del self.records[rec.id]
        if self.on_gone is not None:
            self.on_gone(rec.id)
        return True

    async def change_visibility(self, msg: Message, seconds: float) -> bool:
        await asyncio.sleep(NET)
        rec = self._current(msg)
        if rec is None:
            return False
        self._hide(rec, seconds)
        return True

    # ---- for the screen

    def counts(self) -> tuple[int, int, float]:
        """(visible, in flight, age of the oldest message)."""
        t = now()
        visible = sum(1 for r in self.records.values() if r.visible_at <= t)
        oldest = min((r.sent_at for r in self.records.values()), default=t)
        return visible, len(self.records) - visible, t - oldest


class DeadLetters:
    """The dead-letter queue: where messages that keep failing are parked for a human to look at."""

    def __init__(self, on_park: Callable[[int], None] | None = None) -> None:
        self.on_park = on_park
        self.parked: set[int] = set()

    async def send(self, msg: Message) -> None:
        await asyncio.sleep(NET)
        self.parked.add(msg.id)
        if self.on_park is not None:
            self.on_park(msg.id)


class Dead(asyncio.CancelledError):
    """Raised by a crashed worker's handles: a dead process makes no calls."""


class Queue:
    """What one worker process sees of the queue: nothing works once that process has crashed."""

    def __init__(self, broker: Broker, alive: Callable[[], bool]) -> None:
        self._broker = broker
        self._alive = alive

    def _check(self) -> None:
        if not self._alive():
            raise Dead()

    async def receive(self, wait: float = LONG_POLL) -> Message | None:
        self._check()
        return await self._broker.receive(wait)

    async def delete(self, msg: Message) -> bool:
        self._check()
        return await self._broker.delete(msg)

    async def change_visibility(self, msg: Message, seconds: float) -> bool:
        self._check()
        return await self._broker.change_visibility(msg, seconds)


class Dlq:
    """What one worker process sees of the dead-letter queue."""

    def __init__(self, dead: DeadLetters, alive: Callable[[], bool]) -> None:
        self._dead = dead
        self._alive = alive

    async def send(self, msg: Message) -> None:
        if not self._alive():
            raise Dead()
        await self._dead.send(msg)
