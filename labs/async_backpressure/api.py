"""What your Pipeline gets: `io`, one per process, and the shapes it hands you.

    chunk = await io.read()          the next events from the firehose, oldest first: what has
                                     arrived since the last read (1 to READ_MAX events). It waits
                                     when nothing has arrived. While you do not read, the upstream
                                     keeps what arrives in its own buffer (UPSTREAM_MAX events);
                                     when that is full it drops the oldest: lost, and nobody tells you.
    parsed = io.parse(chunk)         raw -> parsed (no I/O): the same events, now PARSED
    enriched = await io.enrich(b)    one call to the enrichment service: at most ENRICH_MAX events,
                                     PARSED -> ENRICHED; ~20 ms + 0.5 ms an event; it serves
                                     ENRICH_CONCURRENCY calls at once, the rest wait their turn
    await io.write(batch)            one insert into the sink: at most MAX_BATCH ENRICHED events;
                                     ~15 ms + 0.1 ms an event; it runs one write at a time (the rest
                                     wait); raises SinkUnavailable after SINK_TIMEOUT when it is down
    io.shed(events)                  drop events on purpose: counted, never silent. Only LOW events
                                     may be shed; shedding a HIGH one counts as losing it.
    io.memory                        bytes this process holds now (BASE_MEMORY + every event in it)

    Event(id, arrived, priority, kind)   priority HIGH (orders, payments) or LOW (clicks, page views)

Memory: every event costs bytes from the moment you read it until the sink has it (or you shed
it): RAW 4 KiB, PARSED 8 KiB, ENRICHED 16 KiB (the enrichment adds the user, the device, the
geo...). Above MEMORY_LIMIT the process is OOM-killed: every event in it is lost, and it takes
RESTART seconds to come back (a new Pipeline, empty queues) while the upstream buffers.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from core.vtime import now

RAW, PARSED, ENRICHED = range(3)  # what an event is: read, parsed, enriched
HIGH, LOW = range(2)  # priority: HIGH must reach the sink; LOW may be shed (counted)

KIB, MIB = 1024, 1024 * 1024
SIZE = (4 * KIB, 8 * KIB, 16 * KIB)  # bytes an event holds while RAW, PARSED, ENRICHED
BASE_MEMORY = 96 * MIB  # the interpreter, libraries, connection pools: before any event
MEMORY_LIMIT = 256 * MIB  # the container's limit: above it the kernel OOM-kills the process
RESTART = 5.0  # seconds a killed process takes to come back (the container restarts)

READ_MAX = 50  # events one read returns at most
UPSTREAM_MAX = 5_000  # events the upstream keeps for you while you do not read (~5 s)
FRAME = 0.01  # the firehose pushes a frame of events this often

ENRICH_MAX = 100  # events per enrichment call at most
ENRICH_CONCURRENCY = 8  # calls the enrichment service serves at once
ENRICH_BASE, ENRICH_PER = 0.020, 0.0005  # seconds per call, and per event in it

MAX_BATCH = 1_000  # events per write at most (the sink rejects bigger inserts)
SINK_BASE, SINK_PER = 0.015, 0.0001  # seconds per write, and per event in it
SINK_TIMEOUT = 1.0  # a write to a sink that is down fails after this long


def write_time(n: int, slow: float = 1.0) -> float:
    """Seconds the sink takes to write n events when it is `slow` times slower than normal."""
    return (SINK_BASE + n * SINK_PER) * slow


def sink_capacity(slow: float = 1.0) -> float:
    """Events/s the sink can take at best: full batches, one after another."""
    return MAX_BATCH / write_time(MAX_BATCH, slow)


@dataclass(slots=True, eq=False)
class Event:
    id: int
    arrived: float  # when the upstream received it (virtual seconds)
    priority: int  # HIGH or LOW
    kind: int = RAW  # RAW, PARSED or ENRICHED
    done: bool = False  # written, shed or lost: it no longer costs memory


class SinkUnavailable(Exception):
    """The sink did not answer in time (it is down): nothing of this batch was written. Retry it."""


class Killed(asyncio.CancelledError):
    """This process was OOM-killed: every task in it stops."""


# ---------------------------------------------------------------- the world outside your process


class Firehose:
    """The upstream: pushes a frame of events every FRAME seconds and keeps what you have not read
    yet, up to UPSTREAM_MAX events; beyond that it drops the oldest ones (`on_lost(events)`)."""

    def __init__(self, on_lost=None) -> None:
        self.buffer: deque[Event] = deque()
        self.on_lost = on_lost
        self._waiter: asyncio.Future | None = None

    def push(self, events: list[Event]) -> None:
        self.buffer.extend(events)
        over = len(self.buffer) - UPSTREAM_MAX
        if over > 0:
            lost = [self.buffer.popleft() for _ in range(over)]
            if self.on_lost is not None:
                self.on_lost(lost)
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(None)

    async def take(self, most: int = READ_MAX) -> list[Event]:
        while not self.buffer:
            self._waiter = asyncio.get_running_loop().create_future()
            await self._waiter
        buf = self.buffer
        return [buf.popleft() for _ in range(min(most, len(buf)))]


class Enricher:
    """The enrichment service: ENRICH_CONCURRENCY calls at once, first come first served;
    `spike` (set by the scenario) multiplies its latency."""

    def __init__(self) -> None:
        self.slots = asyncio.Semaphore(ENRICH_CONCURRENCY)
        self.spike = 1.0
        self.busy = 0  # calls running now

    async def call(self, n: int) -> None:
        async with self.slots:
            self.busy += 1
            try:
                await asyncio.sleep((ENRICH_BASE + n * ENRICH_PER) * self.spike)
            finally:
                self.busy -= 1


class Sink:
    """The database: one write at a time (the rest wait), `slow` times slower during maintenance,
    and down (every write fails after SINK_TIMEOUT) during an outage."""

    def __init__(self) -> None:
        self.slow = 1.0
        self.down = False
        self.free_at = 0.0  # when the write running now ends
        self.writes: list[tuple] = []  # (start, end, events, ok): for the pictures

    async def call(self, n: int) -> None:
        if self.down:
            await asyncio.sleep(SINK_TIMEOUT)
            self.writes.append((now() - SINK_TIMEOUT, now(), n, False))
            raise SinkUnavailable("the sink did not answer")
        start = max(now(), self.free_at)
        end = self.free_at = start + write_time(n, self.slow)
        await asyncio.sleep(end - now())
        ok = not self.down  # it went down while this write ran: rolled back
        self.writes.append((start, end, n, ok))
        if not ok:
            raise SinkUnavailable("the sink went down during the write")


# ---------------------------------------------------------------- what your code gets


class Services:
    """`io`: the firehose, the enrichment service and the sink, as seen from one process, and
    the memory that process uses. The scenario makes a new one each time the process starts."""

    def __init__(self, firehose: Firehose, enricher: Enricher, sink: Sink, ledger=None) -> None:
        self._firehose, self._enricher, self._sink = firehose, enricher, sink
        self._ledger = ledger  # the scenario's bookkeeping (None in tests)
        self.alive = True
        self.held = [0, 0, 0]  # events held now: RAW, PARSED, ENRICHED
        self.peak = BASE_MEMORY  # the most memory used since the scenario last looked
        self.written = 0
        self.shed_count = 0

    # ---- memory

    @property
    def memory(self) -> int:
        h = self.held
        return BASE_MEMORY + h[0] * SIZE[0] + h[1] * SIZE[1] + h[2] * SIZE[2]

    def _grew(self) -> None:
        m = self.memory
        self.peak = max(self.peak, m)
        if m > MEMORY_LIMIT:
            self.alive = False
            if self._ledger is not None:
                self._ledger.oom(self)
            raise Killed("OOM-killed: the process used more than MEMORY_LIMIT")

    def _check(self) -> None:
        if not self.alive:
            raise Killed("this process was OOM-killed")

    def _settle(self, events: list[Event]) -> None:
        for e in events:
            e.done = True
            self.held[e.kind] -= 1

    # ---- the calls

    async def read(self) -> list[Event]:
        self._check()
        chunk = await self._firehose.take(READ_MAX)
        if not self.alive:  # killed while waiting: the events never reached the process
            self._firehose.buffer.extendleft(reversed(chunk))
            raise Killed("this process was OOM-killed")
        self.held[RAW] += len(chunk)
        if self._ledger is not None:
            self._ledger.read(self, chunk)
        self._grew()
        return chunk

    def parse(self, chunk: list[Event]) -> list[Event]:
        self._check()
        for e in chunk:
            if e.kind != RAW or e.done:
                raise ValueError(f"parse() takes RAW events you hold, not {e!r}")
        for e in chunk:
            e.kind = PARSED
        self.held[RAW] -= len(chunk)
        self.held[PARSED] += len(chunk)
        if self._ledger is not None:
            self._ledger.step(self, chunk, PARSED)
        self._grew()
        return list(chunk)

    async def enrich(self, chunk: list[Event]) -> list[Event]:
        self._check()
        if len(chunk) > ENRICH_MAX:
            raise ValueError(f"enrich() takes at most ENRICH_MAX={ENRICH_MAX} events, not {len(chunk)}")
        for e in chunk:
            if e.kind != PARSED or e.done:
                raise ValueError(f"enrich() takes PARSED events you hold, not {e!r}")
        await self._enricher.call(len(chunk))
        self._check()
        for e in chunk:
            e.kind = ENRICHED
        self.held[PARSED] -= len(chunk)
        self.held[ENRICHED] += len(chunk)
        if self._ledger is not None:
            self._ledger.step(self, chunk, ENRICHED)
        self._grew()
        return list(chunk)

    async def write(self, batch: list[Event]) -> None:
        self._check()
        if len(batch) > MAX_BATCH:
            raise ValueError(f"write() takes at most MAX_BATCH={MAX_BATCH} events, not {len(batch)}")
        for e in batch:
            if e.kind != ENRICHED:
                raise ValueError(f"write() takes ENRICHED events, not {e!r}")
        await self._sink.call(len(batch))
        self._check()
        fresh = [e for e in batch if not e.done]  # the sink is idempotent: a second write is a no-op
        self._settle(fresh)
        self.written += len(fresh)
        if self._ledger is not None:
            self._ledger.written(self, fresh)

    def shed(self, events: list[Event]) -> None:
        self._check()
        fresh = [e for e in events if not e.done]
        self._settle(fresh)
        self.shed_count += len(fresh)
        if self._ledger is not None:
            self._ledger.shed(self, fresh)
