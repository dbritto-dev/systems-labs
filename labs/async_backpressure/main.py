"""Lab async_backpressure: YOUR FILE. Edit it and save; the live window reruns it.

An ingestion process: a firehose pushes ~1,000 events/s at it (30% HIGH: orders, payments;
70% LOW: clicks, page views). Your `Pipeline` reads them (the source), parses them (stage A),
enriches them through a service (stage B, ~25 ms a call) and writes them to a database in
batches (stage C). Every event you hold costs memory (4 KiB raw, 8 parsed, 16 enriched); the
container has 256 MiB, and above that the kernel OOM-kills the process: every event in it is
lost, and a new one starts 5 s later. While you do not read, the upstream keeps what arrives in
its buffer (5,000 events, ~5 s); when it is full it drops the oldest, and nobody tells you.

Right now the stages talk through unbounded asyncio.Queues and write 50 events at a time. When
the sink slows down (the first incident: autovacuum, 16x slower) the queue in front of it grows
without limit, until the OOM kill.

Do the stages in order, in this file:

  Stage 1  Bounded queues: asyncio.Queue(maxsize=QUEUE_SIZE). `put` now waits while the next
           stage is behind, so the slowness travels back to the source, and the source stops
           reading: the upstream buffers instead of your memory. No OOM. But a long slowdown
           fills the upstream's buffer (events lost, silently), and 50-event writes use under
           a third of what the slow sink could take.
  Stage 2  Credits, adaptive batches, shedding:
             - `Credits`: a window of permits; each stage grants them to the one before it, and
               gives them back only once the events have moved on (so they bound the events in
               the queue AND in the hands of the next stage);
             - `take_batch`: wait for one chunk, then take what is already queued: batches grow
               by themselves when the sink (or the enrichment service) is slow;
             - `Pipeline.admit`: when the window is short, shed LOW events (counted, io.shed),
               and keep the last RESERVE credits for HIGH ones: the source waits for those.
           Then wire them into the Pipeline: the `# Stage 2:` comments say where.

What you get (see labs/async_backpressure/api.py):
  chunk = await io.read()         1 to 50 events from the firehose (waits for the next frame)
  parsed = io.parse(chunk)        RAW -> PARSED, no I/O
  enriched = await io.enrich(b)   PARSED -> ENRICHED, at most ENRICH_MAX (100) events a call
  await io.write(batch)           into the sink, at most MAX_BATCH (1,000) ENRICHED events;
                                  raises SinkUnavailable when the sink is down
  io.shed(events)                 drop LOW events on purpose: counted, never silent
  Event(id, arrived, priority, kind), HIGH, LOW

Check yourself:  uv run pytest labs/async_backpressure
Peek at a solution (after trying!):  labs/async_backpressure/reference.py
"""

from __future__ import annotations

import asyncio
from collections import deque  # stage 2: Credits' waiters

from labs.async_backpressure.api import (  # noqa: F401  (HIGH, LOW: stage 2)
    ENRICH_MAX, HIGH, LOW, MAX_BATCH, Event, Services, SinkUnavailable,
)

BATCH = 50  # stage 0: events per write, always
ENRICH_WORKERS = 8  # tasks calling the enrichment service (it serves 8 calls at once)
RETRY_DELAY = 0.5  # seconds between two tries of a write while the sink is down
QUEUE_SIZE = 20  # stage 1: chunks each queue holds at most
WINDOW_A = 3_000  # stage 2: events the parser grants the source (raw, 4 KiB each)
WINDOW_B = 1_000  # stage 2: events the enrichers grant the parser: 8 calls of 100 in flight, and a queue
WINDOW_C = 2 * MAX_BATCH  # stage 2: events the writer grants the enrichers (one batch writing, one filling)
RESERVE = 2_500  # stage 2: the last credits of WINDOW_A are for HIGH events only


class Credits:
    """Stage 2. A window of permits (credits), counted in events: the stage downstream grants them,
    the stage upstream spends them. Like a semaphore that takes n permits at once, or reactive
    streams' request(n).

    Contract:
      - `Credits(window)` starts with `window` credits free; `self.free` is how many are free now.
      - `try_take(n)`: take n credits now if they are free (True), else take nothing (False). Never
        take ahead of someone already waiting in `take`.
      - `await take(n)`: wait until n credits are free, then take them. Waiters are served first
        come, first served. Asking for more than the whole window takes the whole window (else
        it would wait forever).
      - `grant(n)`: give n credits back, and wake the waiters they are enough for, in order.

    Hint: keep a deque of (n, future) waiters. take: if try_take(n), return; else append
    (n, loop.create_future()) and await it. grant: free += n; while the first waiter's n fits,
    popleft it, free -= n, fut.set_result(None) (skip a future that is already done: its task was
    cancelled).
    """

    def __init__(self, window: int) -> None:
        self.window = window
        self.free = window
        self._waiters: deque[tuple[int, asyncio.Future]] = deque()

    def try_take(self, n: int) -> bool:
        raise NotImplementedError("TODO stage 2: Credits.try_take(n)")

    async def take(self, n: int) -> None:
        raise NotImplementedError("TODO stage 2: Credits.take(n)")

    def grant(self, n: int) -> None:
        raise NotImplementedError("TODO stage 2: Credits.grant(n)")


async def take_batch(queue: asyncio.Queue, most: int) -> list[Event]:
    """Stage 2. One batch from a queue of chunks (lists of events): adaptive batching.

    Contract:
      - Wait for the first chunk; then take the chunks that are already queued, without waiting,
        while the batch holds fewer than `most` events.
      - Return at most `most` events; put the rest of the last chunk back (`queue.put_nowait`).
      - So when the next service is fast the batches are small (low latency), and when it is slow
        more events pile up during each call and the next batch is bigger (more throughput):
        a write costs 15 ms + 0.1 ms an event, so 1,000 events cost 115 ms, not 20 x 20 ms.

    Hint: batch = list(await queue.get()); while len(batch) < most and not queue.empty():
    batch += queue.get_nowait(). Then if it is too long, put batch[most:] back and cut it.
    """
    raise NotImplementedError("TODO stage 2: take_batch(queue, most)")


async def write(io: Services, batch: list[Event]) -> None:
    """Write one batch, trying again while the sink is down: an event is never dropped here."""
    while True:
        try:
            await io.write(batch)
            return
        except SinkUnavailable:
            await asyncio.sleep(RETRY_DELAY)


class Pipeline:
    """One process: source -> A (parse) -> B (enrich, ENRICH_WORKERS tasks) -> C (write) -> the sink.

    Contract:
      - `Pipeline(io)` is made each time the process starts (again after an OOM kill), and
        `await pipeline.run()` runs it forever (start the stages in an asyncio.TaskGroup).
      - Every event you read ends up written to the sink, or shed with io.shed() if it is LOW.
      - Memory stays under 80% of the limit; nothing is lost silently.
    """

    def __init__(self, io: Services) -> None:
        self.io = io
        # Stage 1: asyncio.Queue(maxsize=QUEUE_SIZE) for each of the three.
        # Stage 2: plain asyncio.Queue()s again (the credits bound them), plus
        #          self.credits_a = Credits(WINDOW_A), self.credits_b = Credits(WINDOW_B),
        #          self.credits_c = Credits(WINDOW_C).
        self.to_a = asyncio.Queue()  # source -> A: raw chunks
        self.to_b = asyncio.Queue()  # A -> B: parsed chunks
        self.to_c = asyncio.Queue()  # B -> C: enriched chunks

    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.source())
            tg.create_task(self.parser())
            for _ in range(ENRICH_WORKERS):
                tg.create_task(self.enricher())
            tg.create_task(self.writer())

    def admit(self, chunk: list[Event]) -> list[Event]:
        """Stage 2. What the source lets in from one chunk it read; the rest is shed.

        Contract:
          - LOW events only while the source's window has room beyond the reserve:
            credits_a.free - len(chunk) >= RESERVE. Otherwise shed the chunk's LOW events with
            self.io.shed(low) (counted: a deliberate, visible drop) and return only the HIGH ones.
          - HIGH events are never shed: return them, and the source waits for their credits (it
            stops reading; the upstream buffers meanwhile). The reserve is what lets them in while
            the sink is down for a few seconds.
        """
        raise NotImplementedError("TODO stage 2: Pipeline.admit(chunk)")

    async def source(self) -> None:
        while True:
            chunk = await self.io.read()
            # Stage 2: chunk = self.admit(chunk); if it is not empty, await
            #          self.credits_a.take(len(chunk)) then self.to_a.put_nowait(chunk).
            await self.to_a.put(chunk)  # never waits: an unbounded queue

    async def parser(self) -> None:
        while True:
            chunk = await self.to_a.get()
            parsed = self.io.parse(chunk)
            # Stage 2: await self.credits_b.take(len(parsed)); self.to_b.put_nowait(parsed);
            #          then self.credits_a.grant(len(chunk)): the chunk has moved on.
            await self.to_b.put(parsed)

    async def enricher(self) -> None:
        while True:
            # Stage 2: batch = await take_batch(self.to_b, ENRICH_MAX); after the call,
            #          await self.credits_c.take(len(enriched)), put_nowait, and
            #          self.credits_b.grant(len(batch)).
            batch = await self.to_b.get()
            enriched = await self.io.enrich(batch)
            await self.to_c.put(enriched)

    async def writer(self) -> None:
        while True:
            # Stage 2: batch = await take_batch(self.to_c, MAX_BATCH), and after the write,
            #          self.credits_c.grant(len(batch)).
            batch = []
            while len(batch) < BATCH:  # always ~50 events, however slow the sink is
                batch += await self.to_c.get()
            await write(self.io, batch)
