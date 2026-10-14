"""Lab stream_windowing: one endless run on virtual time, handed out a minute at a time.

Phones and servers make ~`rate` purchases a second (Poisson, drifting slowly like real
traffic). Each one is an event stamped with its event time; it goes through a log with
PARTITIONS partitions and reaches the processor 0.05-1.5 s later (a log-normal delay), so
events arrive a little out of order. The processor calls your `Windower.on_event` for each.

Incidents come at random, like in production, and each makes some events arrive late:
  offline   phones come back online and send the purchases they made offline, 6 s to a
            minute and a half old (a subway, flight mode, the OS suspending the app);
  lag       one partition falls 5-20 s behind (a broker GC pause, a slow disk, a rebalance);
  skew      one producer's clock runs 10-45 s behind, so its events look old (NTP down);
  backfill  a replay re-sends events lost upstream, 1-3 minutes old.
The first incident is always phones back online at 0:20-0:30, with events 6-18 s old.

The run never restarts: the processor's state and the clock carry on from minute to minute.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.stream_windowing import lab

LAB = "stream_windowing"
NAMES = ("Windower", "window_of", "WINDOW", "ALLOWED_DELAY", "ALLOWED_LATENESS")
PIECE = 60.0
SAMPLE = 0.5  # how often the processor's state size is recorded
PARTITIONS = 3
SOURCES = 1000  # phones and servers that make purchases
DELAY_MEDIAN, DELAY_MAX = 0.12, 1.5  # seconds through the pipeline, normally
OFFLINE_MIN = 6.0  # a batch from a phone back online is at least this old
OFFLINE_RATE = 0.6  # extra events a second during a batch, as a share of the rate
BACKFILL_MIN = 60.0  # a replayed event is at least this old
BACKFILL_RATE = 0.8

# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "offline", 18.0, "subway")
KINDS = [
    Kind("offline", 0.35, median=8.0, shortest=4.0, longest=15.0, severity=(20.0, 90.0),
         causes=("subway", "flight_mode", "app_suspended", "carrier_outage")),
    Kind("lag", 0.25, median=12.0, shortest=6.0, longest=25.0, severity=(5.0, 20.0),
         causes=("broker_gc", "slow_disk", "rebalance", "hot_partition")),
    Kind("skew", 0.2, median=12.0, shortest=6.0, longest=25.0, severity=(10.0, 45.0),
         causes=("ntp_down", "vm_resume", "bad_rtc", "container_clock")),
    Kind("backfill", 0.2, median=8.0, shortest=4.0, longest=15.0, severity=(90.0, 180.0),
         causes=("replay", "partner_upload", "mirror_catchup", "restore")),
]
MEAN_GAP = 25.0
QUIET = 45.0  # calm after an incident: its windows become final, then a 20 s baseline

# What made an event late (events table), and what the processor did with it.
NORMAL, OFFLINE, LAG, SKEW, BACKFILL = range(5)
ON_TIME, UPDATED, SIDE, WRONG, DROPPED = range(5)  # counted before its window was emitted; counted
# in an update; parked in the side output; counted in another window; in no count at all


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def lagging_partition(t0: float) -> int:
    """Which partition lags in a lag incident starting at t0 (the screen needs it too)."""
    return int(round(t0 * 10)) % PARTITIONS


def skewed(source: int) -> bool:
    """The producers whose clock is behind in a skew incident: one in four."""
    return source % 4 == 0


class Event:
    """What your `on_event` gets: `id`, `time` (the event time) and `source`."""

    __slots__ = ("id", "time", "source", "born", "kind", "partition")

    def __init__(self, eid: int, time: float, source: int, born: float, kind: int, partition: int) -> None:
        self.id, self.time, self.source = eid, time, source
        self.born, self.kind, self.partition = born, kind, partition

    def __repr__(self) -> str:
        return f"Event(id={self.id}, time={self.time:.3f})"


class Sink:
    """The dashboard (emit) and the side output: records what your code sends."""

    def __init__(self, sim: "_Sim") -> None:
        self.sim = sim
        self.shown: set[float] = set()  # windows already on the dashboard
        self.call_emits: list[tuple[float, int]] = []
        self.call_side: list = []

    def emit(self, start: float, count: int) -> None:
        start, count = float(start), int(count)
        first = start not in self.shown
        self.shown.add(start)
        self.sim.emits.append((now(), start, count, first))
        self.call_emits.append((start, count))

    def side_output(self, event) -> None:
        self.call_side.append(event)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.rng = random.Random(seed * 7 + 3)
        self.sink = Sink(self)
        self.proc = code.Windower(self.sink)
        self.next_id = 0
        self.max_et = -math.inf  # the watermark the lab judges by: max event time - lab.DELAY
        self.now_kind: dict[str, Planned] = {}  # incidents going on, by kind
        # (arrived, id, event time, born, source, kind, how late: watermark - window end, outcome, partition)
        self.events: list[tuple] = []
        self.emits: list[tuple] = []  # (time, window start, count, first emission of that window)
        self.state: list[tuple] = []  # (time, windows kept, the lab's watermark)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []

    def event(self, et: float, source: int, born: float, kind: int, partition: int) -> Event:
        self.next_id += 1
        return Event(self.next_id, et, source, born, kind, partition)

    def deliver(self, ev: Event) -> None:
        """The event reaches the processor: run your code, then see where the event went."""
        if self.bugs:
            return
        at = now()
        self.max_et = max(self.max_et, ev.time)
        start = math.floor(ev.time / lab.WINDOW) * lab.WINDOW
        late = self.max_et - lab.DELAY - (start + lab.WINDOW)
        here = math.floor(at / lab.WINDOW) * lab.WINDOW
        proc, sink = self.proc, self.sink
        before = proc.windows.get(start, 0)
        before_here = proc.windows.get(here, 0)
        shown = start in sink.shown
        sink.call_emits.clear()
        sink.call_side.clear()
        try:
            proc.on_event(ev, at)
        except Exception as exc:  # a bug in the code under test (or a TODO): surface it
            self.bugs.append(exc)
            return
        mine = [c for s, c in sink.call_emits if s == start]
        if any(e is ev for e in sink.call_side):
            outcome = SIDE
        elif mine and mine[-1] == before + 1:
            outcome = UPDATED if shown else ON_TIME
        elif proc.windows.get(start, 0) == before + 1 and not shown:
            outcome = ON_TIME
        elif here != start and proc.windows.get(here, 0) == before_here + 1:
            outcome = WRONG
        elif here != start and any(s == here and c == before_here + 1 for s, c in sink.call_emits):
            outcome = WRONG
        else:
            outcome = DROPPED
        self.events.append((at, ev.id, ev.time, ev.born, ev.source, ev.kind, late, outcome, ev.partition))

    def send(self, ev: Event, delay: float) -> None:
        asyncio.get_running_loop().call_later(delay, self.deliver, ev)

    def delay(self) -> float:
        return min(DELAY_MAX, self.rng.lognormvariate(math.log(DELAY_MEDIAN), 0.7))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            source = self.rng.randrange(SOURCES)
            part = self.rng.randrange(PARTITIONS)
            et, kind, extra = t, NORMAL, 0.0
            lag = self.now_kind.get("lag")
            if lag is not None and part == lagging_partition(lag.t0):
                kind, extra = LAG, lag.severity * (0.85 + 0.15 * self.rng.random())
            skew = self.now_kind.get("skew")
            if skew is not None and skewed(source):
                kind, et = SKEW, t - skew.severity
            self.send(self.event(et, source, t, kind, part), self.delay() + extra)

    async def burst(self, inc: Planned, kind: int, share: float, oldest: float, youngest: float) -> None:
        """Extra events arriving during [t0, t1] with old event times: a batch, or a replay."""
        rng = random.Random(self.seed * 13 + int(inc.t0 * 10))
        t = now()
        while True:
            t += rng.expovariate(self.rate * share)
            if t >= inc.t1:
                return
            await asyncio.sleep(t - now())
            age = rng.uniform(youngest, min(oldest, t - 1.0))
            ev = self.event(t - age, rng.randrange(SOURCES), t, kind, rng.randrange(PARTITIONS))
            self.send(ev, self.delay() * 0.3)

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            self.now_kind[inc.kind] = inc
            if inc.kind == "offline":
                await self.burst(inc, OFFLINE, OFFLINE_RATE, inc.severity, OFFLINE_MIN)
            elif inc.kind == "backfill":
                await self.burst(inc, BACKFILL, BACKFILL_RATE, inc.severity, BACKFILL_MIN)
            await asyncio.sleep(inc.t1 - now())
            self.now_kind.pop(inc.kind, None)

    async def sampler(self) -> None:
        while True:
            self.state.append((now(), len(self.proc.windows), self.max_et - lab.DELAY))
            await asyncio.sleep(SAMPLE)

    @staticmethod
    def take(rows: list[tuple], a: float, b: float) -> list[tuple]:
        """Remove rows before b (time in column 0); return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[0] < b), key=lambda r: r[0])
        rows[:] = [r for r in rows if r[0] >= b]
        return [r for r in out if r[0] >= a]


def stream(variant="main", seed: int = 1, rate: float = 40.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what happened in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    sim.spawn(s.sampler())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b)
            if s.bugs:
                raise s.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    "events": s.take(s.events, a, b),
                    "emits": s.take(s.emits, a, b),
                    "state": s.take(s.state, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
