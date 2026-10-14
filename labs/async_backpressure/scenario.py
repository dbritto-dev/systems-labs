"""Lab async_backpressure: one endless run on virtual time, handed out a minute at a time.

A firehose pushes ~`rate` events a second (a frame every 10 ms; 30% HIGH: orders and payments,
70% LOW: clicks and page views) into one ingestion process that runs your `Pipeline`: a source
reads them, stage A parses, stage B enriches them through a service, stage C writes them in
batches to a sink (a database). Every event the process holds costs memory; above MEMORY_LIMIT
the process is OOM-killed: every event in it is lost, and a new one starts RESTART seconds later
(a new Pipeline), while the upstream keeps what arrives in its buffer, and drops the oldest when
it is full.

Incidents come at random, like in production: the sink slows down (autovacuum, a compaction,
throttling, a backup), the enrichment service has a latency spike (GC pauses, a cold cache, its
database failing over), the upstream bursts (a backfill, a viral moment), or the sink is down
for a few seconds (a failover, a proxy restart). The first incident is always the sink 16x
slower at 0:20-0:50.

The run never restarts: the upstream, the services and the clock carry on from one minute to
the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, rate_at, schedule
from core.vtime import VirtualRun, now
from labs.async_backpressure.api import (
    FRAME, HIGH, LOW, PARSED, RESTART, Enricher, Event, Firehose, Killed, Services, Sink,
)

LAB = "async_backpressure"
NAMES = ("Pipeline", "Credits", "take_batch")
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
TICK = 0.1  # how often the process is recorded
SAMPLE = 10  # one event in SAMPLE is traced end to end (for latencies and the pictures)
HIGH_SHARE = 0.3  # HIGH events: orders, payments, sign-ups; the rest are LOW

# What became of a traced event.
PENDING, WRITTEN, SHED, LOST = range(4)
# Where an event was lost.
NOWHERE, UPSTREAM, OOM, DROPPED = range(4)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 50.0, "slow", 16.0, "vacuum")
KINDS = [
    Kind("slow", 0.3, median=25.0, shortest=12.0, longest=45.0, severity=(4.0, 16.0),
         causes=("vacuum", "compaction", "throttled", "backup")),
    Kind("spike", 0.25, median=15.0, shortest=8.0, longest=30.0, severity=(5.0, 20.0),
         causes=("gc_pause", "cold_cache", "db_failover", "noisy_neighbour")),
    Kind("burst", 0.25, median=20.0, shortest=10.0, longest=30.0, severity=(2.0, 3.0),
         causes=("backfill", "viral", "replay", "campaign")),
    Kind("outage", 0.2, median=8.0, shortest=4.0, longest=12.0, severity=(1.0, 1.0),
         causes=("failover", "proxy_restart", "network", "cert_expired")),
]
MEAN_GAP = 30.0
QUIET = 40.0  # calm after an incident: its after-window, then 15 s of baseline before the next


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    """The world around your process, and the books: what arrived, what was written, shed or lost."""

    def __init__(self, code, seed: int, rate: float) -> None:
        self.code = code
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 13 + 5)
        self.firehose = Firehose(on_lost=self.lost_upstream)
        self.enricher = Enricher()
        self.sink = Sink()
        self.burst = 1.0
        self.ids = itertools.count(1)
        self.svc: Services | None = None  # the process running now (None while it restarts)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        # Counters since the last tick.
        self.n = {k: 0 for k in ("arrived", "read", "written", "shed", "lost_up", "lost_oom", "lost_high", "ooms")}
        self.peak = 0  # the most memory used since the last tick (an OOM-killed process included)
        self.killed = asyncio.Event()
        # Traced events: id -> [arrived, read, parsed, enriched, end, outcome, priority, where lost].
        self.trace: dict[int, list] = {}
        self.inside: dict[int, Event] = {}  # traced events the running process holds
        self.ticks: list[tuple] = []
        self.writes: list[tuple] = []

    # ---- the upstream

    async def pump(self) -> None:
        rng = random.Random(self.seed * 17 + 3)
        acc = 0.0
        while True:
            await asyncio.sleep(FRAME)
            t = now()
            acc += rate_at(self.rate, t, self.seed) * self.burst * FRAME * rng.uniform(0.6, 1.4)
            k = int(acc)
            acc -= k
            frame = []
            for _ in range(k):
                i = next(self.ids)
                e = Event(i, t, HIGH if rng.random() < HIGH_SHARE else LOW)
                frame.append(e)
                if i % SAMPLE == 0:
                    self.trace[i] = [t, None, None, None, None, PENDING, e.priority, NOWHERE]
            self.n["arrived"] += k
            self.firehose.push(frame)

    def lost_upstream(self, events: list[Event]) -> None:
        self.n["lost_up"] += len(events)
        for e in events:
            e.done = True
            self._end(e, LOST, UPSTREAM)

    # ---- the books (Services calls these)

    def _end(self, e: Event, outcome: int, where: int = NOWHERE) -> None:
        tr = self.trace.get(e.id)
        if tr is not None and tr[5] == PENDING:
            tr[4], tr[5], tr[7] = now(), outcome, where
        self.inside.pop(e.id, None)

    def read(self, svc: Services, chunk: list[Event]) -> None:
        self.n["read"] += len(chunk)
        t = now()
        for e in chunk:
            if e.id % SAMPLE == 0:
                tr = self.trace.get(e.id)
                if tr is not None:
                    tr[1] = t
                    self.inside[e.id] = e

    def step(self, svc: Services, chunk: list[Event], kind: int) -> None:
        col = 2 if kind == PARSED else 3
        t = now()
        for e in chunk:
            if e.id % SAMPLE == 0 and e.id in self.trace:
                self.trace[e.id][col] = t

    def written(self, svc: Services, events: list[Event]) -> None:
        self.n["written"] += len(events)
        for e in events:
            if e.id % SAMPLE == 0:
                self._end(e, WRITTEN)

    def shed(self, svc: Services, events: list[Event]) -> None:
        for e in events:
            if e.priority == LOW:
                self.n["shed"] += 1
                if e.id % SAMPLE == 0:
                    self._end(e, SHED)
            else:  # a HIGH event must reach the sink: dropping one is losing it
                self.n["lost_high"] += 1
                if e.id % SAMPLE == 0:
                    self._end(e, LOST, DROPPED)

    def oom(self, svc: Services) -> None:
        self.n["lost_oom"] += sum(svc.held)
        self.n["ooms"] += 1
        self.peak = max(self.peak, svc.peak)
        for e in list(self.inside.values()):
            self._end(e, LOST, OOM)
        self.inside.clear()
        svc.held = [0, 0, 0]
        self.killed.set()

    # ---- the process

    async def supervisor(self) -> None:
        """Start the process; when it is OOM-killed, start a new one RESTART seconds later."""
        while True:
            self.killed.clear()
            svc = self.svc = Services(self.firehose, self.enricher, self.sink, ledger=self)
            try:
                pipeline = self.code.Pipeline(svc)
                task = asyncio.ensure_future(pipeline.run())
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return
            killed = asyncio.ensure_future(self.killed.wait())
            await asyncio.wait([task, killed], return_when=asyncio.FIRST_COMPLETED)
            if not self.killed.is_set():
                killed.cancel()
                exc = None if task.cancelled() else task.exception()
                while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
                    exc = exc.exceptions[0]
                if exc is None or isinstance(exc, Killed):
                    exc = RuntimeError(lab_text(LAB).STRINGS["returned"])
                self.bugs.append(exc)
                return
            task.cancel()
            try:
                await task
            except BaseException:  # the killed process's own errors do not matter
                pass
            self.svc = None
            await asyncio.sleep(RESTART)

    async def ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK)
            svc = self.svc
            n = self.n
            mem = svc.memory if svc is not None else 0
            peak = max(self.peak, svc.peak if svc is not None else 0)
            if svc is not None:
                svc.peak = mem
            self.peak = 0
            held = svc.held if svc is not None else (0, 0, 0)
            writes = [w for w in self.sink.writes if w[3]]
            self.writes += self.sink.writes
            self.sink.writes = []
            self.ticks.append((now(), n["arrived"], n["read"], n["written"], n["shed"], n["lost_up"],
                               n["lost_oom"], n["lost_high"], n["ooms"], peak, mem, len(self.firehose.buffer),
                               held[0], held[1], held[2], int(svc is not None), len(writes),
                               sum(w[2] for w in writes), self.enricher.busy))
            for k in n:
                n[k] = 0

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "slow":
                    self.sink.slow = inc.severity
                case "spike":
                    self.enricher.spike = inc.severity
                case "burst":
                    self.burst = inc.severity
                case "outage":
                    self.sink.down = True
            await asyncio.sleep(inc.t1 - now())
            self.sink.slow = self.enricher.spike = self.burst = 1.0
            self.sink.down = False

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]

    def take_trace(self, a: float, b: float) -> list[tuple]:
        """Traced events that arrived in [a, b): (arrived, id, read, parsed, enriched, end, outcome,
        priority, where lost). `end` is None for one still on its way."""
        out = []
        for i in [i for i, tr in self.trace.items() if tr[0] < b]:
            tr = self.trace.pop(i)
            if tr[0] >= a:
                out.append((tr[0], i, tr[1], tr[2], tr[3], tr[4], tr[5], tr[6], tr[7]))
        out.sort()
        return out


def stream(variant="main", seed: int = 1, rate: float = 1000.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.pump())
    sim.spawn(s.supervisor())
    sim.spawn(s.ticker())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (t, arrived, read, written, shed, lost upstream, lost in an OOM kill, HIGH dropped,
                    #  OOM kills, peak memory, memory, upstream buffer, raw, parsed, enriched held,
                    #  process up, writes, events written by them, enrichment calls running):
                    #  every TICK; the counts are since the previous tick
                    "ticks": s.take(s.ticks, 0, a, b),
                    # (arrived, id, read, parsed, enriched, end, outcome, priority, where lost):
                    #  one event in SAMPLE
                    "events": s.take_trace(a, b),
                    # (start, end, events, ok): every write the sink ran
                    "writes": s.take(s.writes, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 1000.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
