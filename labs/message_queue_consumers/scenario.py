"""Lab message_queue_consumers: one endless run on virtual time, handed out a minute at a time.

Producers send ~`rate` jobs a second to a queue like SQS. Seven worker processes, six jobs at
a time each, receive them and call your `Consumer.process(msg)`. A job takes ~0.1 s.

Incidents come at random, like in production: worker processes crash mid-job (a deploy, an
OOM kill, a spot instance taken back) and restart 2 s later; a downstream gets slow, so some
jobs take longer than the visibility timeout; a bad producer deploy sends poison messages that
always fail; or the downstream blips (every call fails for a second or three). The first
incident is always a poison batch at 0:20-0:30.

The run never restarts: the queue, its messages and the clock carry on from minute to minute.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.message_queue_consumers import lab
from labs.message_queue_consumers.api import Broker, Dead, DeadLetters, Dlq, JobFailed, Queue

LAB = "message_queue_consumers"
NAMES = ("Consumer",)
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a process() call still running after this long is a bug
RESTART = 2.0  # seconds a crashed worker process takes to come back
SAMPLE = 0.5  # how often the queue's depth is recorded
JOB_TIME = 0.08  # median seconds a job takes
POISON_TIME = 2.5  # a poison job hangs this long (a lookup that times out), then fails
BLIP_TIME = 0.05  # a call to a downstream that is down fails this fast
SLOW_SHARE = 0.1  # share of jobs that hit the slow downstream during a slow incident

# Job outcomes (jobs table) and try results (tries table).
DONE, LOST, PARKED, QUEUED = range(4)
OK, FAILED, CRASHED = range(3)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "poison", 0.05, "staging_ids")
KINDS = [
    Kind("crash", 0.3, median=8.0, shortest=4.0, longest=15.0, severity=(0.08, 0.2),
         causes=("deploy", "oom", "spot", "node_drain")),
    Kind("slow", 0.25, median=10.0, shortest=5.0, longest=20.0, severity=(2.5, 5.0),
         causes=("migration", "throttling", "big_exports", "cold_cache")),
    Kind("poison", 0.25, median=8.0, shortest=4.0, longest=14.0, severity=(0.03, 0.06),
         causes=("staging_ids", "schema_change", "deleted_records", "truncated")),
    Kind("blip", 0.2, median=2.0, shortest=1.0, longest=3.0, severity=(1.0, 1.0),
         causes=("failover", "dns", "cert_rotation", "conn_reset")),
]
MEAN_GAP = 25.0
QUIET = 25.0  # calm after an incident: 15 s of baseline before the next + time to settle


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Job:
    __slots__ = ("id", "sent", "first_recv", "receives", "tries", "running", "holders", "ok", "dup",
                 "poison", "slow", "gone", "parked", "finished")

    def __init__(self, mid: int, sent: float, poison: bool) -> None:
        self.id, self.sent, self.poison = mid, sent, poison
        self.first_recv: float | None = None
        self.receives = self.tries = self.running = self.holders = 0
        self.ok = self.dup = self.gone = self.parked = self.finished = False
        self.slow: bool | None = None  # decided at its first try during a slow incident


class _Process:
    """One worker process: SLOTS loops that receive and call your Consumer. A crash kills them all."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.alive = True
        self.tasks: list[asyncio.Task] = []
        self.holding: dict[int, float] = {}  # slot -> when its process() call started


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code = code
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 7 + 3)
        self.broker = Broker(on_receive=self.on_receive, on_gone=self.on_gone)
        self.dead = DeadLetters(on_park=self.on_park)
        self.jobs: dict[int, _Job] = {}
        self.procs: list[_Process] = []
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.poison_share = 0.0
        self.slow_time = 0.0  # seconds a slow job takes (0: the downstream is fine)
        self.blip = False  # every downstream call fails
        self.done_jobs: list[tuple] = []  # (id, sent, first_recv, end, outcome, receives, tries, dup, poison)
        self.tries: list[tuple] = []  # (start, id, receive_count, end, result, process, dup, poison)
        self.depth: list[tuple] = []  # (t, visible, in flight, oldest age, busy, down)
        self.downs: list[tuple] = []  # (t0, process, t1)

    # ---- the queue tells us what happens to messages

    def on_receive(self, rec) -> None:
        j = self.jobs.get(rec.id)
        if j is None:
            return
        j.receives = rec.receives
        if j.first_recv is None:
            j.first_recv = now()

    def on_gone(self, mid: int) -> None:
        j = self.jobs.get(mid)
        if j is not None:
            j.gone = True
            self.maybe_finish(j)

    def on_park(self, mid: int) -> None:
        j = self.jobs.get(mid)
        if j is not None:
            j.parked = True

    def maybe_finish(self, j: _Job) -> None:
        if j.finished or not j.gone or j.holders or j.running:
            return
        j.finished = True
        del self.jobs[j.id]
        outcome = DONE if j.ok else PARKED if j.parked else LOST
        self.done_jobs.append((j.id, j.sent, j.first_recv, now(), outcome, j.receives, j.tries, j.dup, j.poison))

    # ---- producers

    async def producers(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            poison = self.poison_share > 0 and rng.random() < self.poison_share
            mid = self.broker.send({"order": rng.randrange(1, 1_000_000), "kind": "invoice"})
            self.jobs[mid] = _Job(mid, now(), poison)

    # ---- the job your consumer runs: handle(msg)

    def job_time(self, j: _Job) -> tuple[float, bool]:
        """How long this try takes, and whether it fails."""
        if self.blip:
            return BLIP_TIME, True
        if j.poison:
            return POISON_TIME * (0.9 + 0.2 * self.rng.random()), True
        if self.slow_time:
            if j.slow is None:
                j.slow = self.rng.random() < SLOW_SHARE
            if j.slow:
                return self.slow_time * (0.8 + 0.4 * self.rng.random()), False
        return min(0.5, JOB_TIME * math.exp(0.4 * self.rng.gauss(0, 1))), False

    def handler(self, proc: _Process):
        async def handle(msg) -> None:
            if not proc.alive:
                raise Dead()
            j = self.jobs.get(msg.id)
            if j is None:  # already finished: nothing to track (and nothing to do)
                return
            dup = j.running > 0 or j.ok
            j.running += 1
            j.tries += 1
            j.dup |= dup
            start, result = now(), CRASHED
            try:
                seconds, fails = self.job_time(j)
                await asyncio.sleep(seconds)
                if fails:
                    result = FAILED
                    raise JobFailed(f"job {msg.id} failed")
                result = OK
                j.ok = True
            finally:
                j.running -= 1
                self.tries.append((start, msg.id, msg.receive_count, now(), result, proc.index, dup, j.poison))
                self.maybe_finish(j)

        return handle

    # ---- workers

    def start_process(self, index: int) -> None:
        proc = _Process(index)
        alive = lambda: proc.alive  # noqa: E731
        consumer = self.code.Consumer(Queue(self.broker, alive), Dlq(self.dead, alive), self.handler(proc))
        if index < len(self.procs):
            self.procs[index] = proc
        else:
            self.procs.append(proc)
        loop = asyncio.get_running_loop()
        proc.tasks = [loop.create_task(self.slot(proc, k, consumer)) for k in range(lab.SLOTS)]

    async def slot(self, proc: _Process, k: int, consumer) -> None:
        queue = Queue(self.broker, lambda: proc.alive)
        while True:
            msg = await queue.receive()
            if msg is None:
                continue
            j = self.jobs.get(msg.id)
            if j is not None:
                j.holders += 1
            proc.holding[k] = now()
            try:
                await consumer.process(msg)
            except JobFailed:
                pass  # it stays in the queue and comes back when its visibility timeout runs out
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
            finally:
                proc.holding.pop(k, None)
                if j is not None:
                    j.holders -= 1
                    self.maybe_finish(j)

    async def workers(self) -> None:
        for i in range(lab.PROCESSES):
            self.start_process(i)

    async def crash(self, index: int) -> None:
        proc = self.procs[index]
        if not proc.alive:
            return
        proc.alive = False
        for task in proc.tasks:
            task.cancel()
        self.downs.append((now(), index, now() + RESTART))
        await asyncio.sleep(RESTART)
        self.start_process(index)

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "crash":
                    while now() < inc.t1:  # each process dies at random, `severity` times a second
                        for i in range(lab.PROCESSES):
                            if self.procs[i].alive and self.rng.random() < inc.severity * 0.25:
                                asyncio.ensure_future(self.crash(i))
                        await asyncio.sleep(0.25)
                case "slow":
                    self.slow_time = inc.severity
                case "poison":
                    self.poison_share = inc.severity
                case "blip":
                    self.blip = True
            await asyncio.sleep(max(0.0, inc.t1 - now()))
            self.slow_time, self.poison_share, self.blip = 0.0, 0.0, False

    async def sampler(self) -> None:
        while True:
            visible, inflight, oldest = self.broker.counts()
            busy = sum(len(p.holding) for p in self.procs)
            down = sum(1 for p in self.procs if not p.alive)
            self.depth.append((now(), visible, inflight, oldest, busy, down))
            await asyncio.sleep(SAMPLE)

    def stuck_jobs(self, b: float) -> list[tuple]:
        """Messages sent before b that are still in the queue: handed out once, as QUEUED."""
        out = []
        for j in self.jobs.values():
            if j.sent < b and not j.finished:
                j.finished = True  # never handed out again; the world keeps it as still queued
                out.append((j.id, j.sent, j.first_recv, None, QUEUED, j.receives, j.tries, j.dup, j.poison))
        return out

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 40.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.workers())
    sim.spawn(s.producers())
    sim.spawn(s.chaos())
    sim.spawn(s.sampler())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            limit = b + DRAIN - STUCK
            if any(t < limit for p in s.procs for t in p.holding.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            jobs = s.take(s.done_jobs, 1, a, b) + s.stuck_jobs(b)
            jobs.sort(key=lambda r: r[1])
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (id, sent, first received, end or None, outcome, receives, tries, duplicate, poison)
                    "jobs": jobs,
                    # (start, id, receive count, end, result, process, duplicate, poison)
                    "tries": s.take(s.tries, 0, a, b),
                    # (t, visible, in flight, oldest age, busy slots, processes down)
                    "depth": s.take(s.depth, 0, a, b),
                    # (t0, process, t1)
                    "downs": s.take(s.downs, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 40.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
