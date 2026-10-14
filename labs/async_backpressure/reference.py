"""Lab async_backpressure: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
from collections import deque

from labs.async_backpressure.api import ENRICH_MAX, HIGH, LOW, MAX_BATCH, Event, Services, SinkUnavailable

BATCH = 50  # stage 0: events per write, always
ENRICH_WORKERS = 8  # tasks calling the enrichment service (it serves 8 calls at once)
RETRY_DELAY = 0.5  # seconds between two tries of a write while the sink is down
QUEUE_SIZE = 20  # stage 1: chunks each queue holds at most
WINDOW_A = 3_000  # stage 2: events the parser grants the source (raw, 4 KiB each)
WINDOW_B = 1_000  # stage 2: events the enrichers grant the parser: 8 calls of 100 in flight, and a queue
WINDOW_C = 2 * MAX_BATCH  # stage 2: events the writer grants the enrichers (one batch writing, one filling)
RESERVE = 2_500  # stage 2: the last credits of WINDOW_A are for HIGH events only


class Credits:
    def __init__(self, window: int) -> None:
        self.window = window
        self.free = window
        self._waiters: deque[tuple[int, asyncio.Future]] = deque()

    def try_take(self, n: int) -> bool:
        if self._waiters or self.free < n:
            return False  # never jump ahead of someone already waiting
        self.free -= n
        return True

    async def take(self, n: int) -> None:
        n = min(n, self.window)  # more than the whole window would wait forever
        if self.try_take(n):
            return
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append((n, fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.grant(n)  # granted just as we were cancelled: give it back
            elif (n, fut) in self._waiters:
                self._waiters.remove((n, fut))
            raise

    def grant(self, n: int) -> None:
        self.free += n
        while self._waiters and self._waiters[0][0] <= self.free:
            k, fut = self._waiters.popleft()
            if not fut.done():  # skip a waiter that was cancelled
                self.free -= k
                fut.set_result(None)


async def take_batch(queue: asyncio.Queue, most: int) -> list[Event]:
    batch = list(await queue.get())  # wait for the first chunk ...
    while len(batch) < most and not queue.empty():  # ... then take what is already there, no waiting
        batch += queue.get_nowait()
    if len(batch) > most:
        queue.put_nowait(batch[most:])  # the rest waits for the next batch
        del batch[most:]
    return batch


async def write(io: Services, batch: list[Event]) -> None:
    """Write one batch, trying again while the sink is down: an event is never dropped here."""
    while True:
        try:
            await io.write(batch)
            return
        except SinkUnavailable:
            await asyncio.sleep(RETRY_DELAY)


class Pipeline:
    def __init__(self, io: Services) -> None:
        self.io = io
        # Credits bound every event between two stages, in the queue and in the hands of the stage
        # that has it, so memory has a ceiling: 3,000 x 4 + 1,000 x 8 + 2,000 x 16 KiB = ~51 MiB.
        self.to_a, self.to_b, self.to_c = asyncio.Queue(), asyncio.Queue(), asyncio.Queue()
        self.credits_a = Credits(WINDOW_A)
        self.credits_b = Credits(WINDOW_B)
        self.credits_c = Credits(WINDOW_C)

    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.source())
            tg.create_task(self.parser())
            for _ in range(ENRICH_WORKERS):
                tg.create_task(self.enricher())
            tg.create_task(self.writer())

    def admit(self, chunk: list[Event]) -> list[Event]:
        # LOW events only while the window has room beyond the reserve; else shed them, counted.
        # HIGH events are always admitted: the source waits for their credits (the upstream
        # buffers meanwhile), and the reserve is what lets them in during an outage.
        low = [e for e in chunk if e.priority == LOW]
        if low and self.credits_a.free - len(chunk) < RESERVE:
            self.io.shed(low)
            return [e for e in chunk if e.priority == HIGH]
        return chunk

    async def source(self) -> None:
        while True:
            chunk = self.admit(await self.io.read())
            if chunk:
                await self.credits_a.take(len(chunk))
                self.to_a.put_nowait(chunk)

    async def parser(self) -> None:
        while True:
            chunk = await self.to_a.get()
            parsed = self.io.parse(chunk)
            await self.credits_b.take(len(parsed))
            self.to_b.put_nowait(parsed)
            self.credits_a.grant(len(chunk))

    async def enricher(self) -> None:
        while True:
            batch = await take_batch(self.to_b, ENRICH_MAX)  # bigger calls when the service is slow
            enriched = await self.io.enrich(batch)
            await self.credits_c.take(len(enriched))
            self.to_c.put_nowait(enriched)
            self.credits_b.grant(len(batch))

    async def writer(self) -> None:
        while True:
            batch = await take_batch(self.to_c, MAX_BATCH)  # bigger writes when the sink is slow
            await write(self.io, batch)
            self.credits_c.grant(len(batch))
