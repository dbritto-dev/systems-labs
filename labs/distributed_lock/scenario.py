"""Lab distributed_lock: workers take a lock before writing to shared storage, one endless run on virtual time.

A lock service, 4 workers and a storage service on a simulated network (~50 ms per message).
Clients hand out jobs (regenerate the shared report: ~0.8 a second, to any healthy worker); a
worker takes the lock, writes the report in 3 parts, releases it and answers. Only one job may
write at a time: a write from a job that has lost the lock, landing after a newer holder wrote,
corrupts the report.

Incidents, like in production, hit the job that holds the lock, at the worst moment (the
first write or grant after their planned start; they last as long as planned from there):
  pause      the next worker to write freezes (GC pause, VM migration, swapped out) until it
             ends; its messages wait, then go out as if nothing happened
  crash      the next worker to get the lock dies with it (it restarts, empty, at the end)
  delay      the next write sits in the network (retransmits, a congested link) until it ends
  partition  the next worker to write is cut off from the lock service (not from the storage)
The load balancer stops sending jobs to a frozen, dead or cut-off worker. The first incident
is always a 10 s pause, from the first write after 0:20.

The checker watches the messages, outside your code: which job the lock service granted the
lock to (an `acquire_ok`), and which writes the storage accepted (a `write_ok`). A write is
*stale* when a job granted the lock later has already had a write accepted.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Delivery, Message, Network
from core.vtime import VirtualRun, now

LAB = "distributed_lock"
NAMES = ("LockService", "Worker", "Storage")
PIECE = 60.0
DRAIN = 30.0  # simulate this far past a minute before handing it out (a held write can take ~25 s)
IDS = ("lock", "w1", "w2", "storage", "w3", "w4")  # in this order on the cluster grid: 2 rows of 3
LOCK, STORAGE = 0, 3
WORKERS = (1, 2, 4, 5)
JOB_DEADLINE = 10.0  # a client gives up on a job after this long
LATENCY = 0.05
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "pause", 1.0, "gc_pause")
KINDS = [
    Kind("pause", 0.3, median=8.0, shortest=5.0, longest=20.0, causes=(
        "gc_pause", "vm_migration", "swapping", "cpu_throttle")),
    Kind("crash", 0.25, median=10.0, shortest=5.0, longest=25.0, causes=(
        "oom_kill", "kernel_panic", "spot_reclaim", "bad_deploy")),
    Kind("delay", 0.25, median=6.0, shortest=4.0, longest=15.0, causes=(
        "retransmits", "congested_link", "proxy_queue")),
    Kind("partition", 0.2, median=10.0, shortest=5.0, longest=25.0, causes=(
        "switch_port", "firewall_rule", "dns")),
]
MEAN_GAP = 30.0
QUIET = 33.0  # calm after an incident: 10 s to judge it, 15 s of baseline before the next, 5 s to arm
ARM_MAX = 5.0  # an incident waits this long for its moment (a write, a grant), else it is skipped

# Message kinds in the "msgs" table.
LOCK_MSG, WRITE_REPLY, JOB_MSG = range(3)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Void:
    """Where a crashed worker's messages go: nowhere."""

    def __init__(self) -> None:
        self.bugs: list[BaseException] = []

    def send(self, src: str, dest: str, body) -> None:
        pass


class _Net(Network):
    """The simulated network, which also freezes, cuts off or delays what an incident hits."""

    def __init__(self, sim: "_Sim", seed: int) -> None:
        super().__init__(latency=LATENCY, jitter=0.2, seed=seed)
        self.sim = sim
        self.down: set[str] = set()  # crashed: nothing in or out
        self.paused: dict[str, float] = {}  # frozen until then: everything in or out waits
        self.cut_off: set[str] = set()  # cannot reach the lock service (nor it them)

    def cut(self, a: str, b: str) -> bool:
        if a in self.down or b in self.down:
            return True
        if (a == "lock" and b in self.cut_off) or (b == "lock" and a in self.cut_off):
            return True
        return super().cut(a, b)

    def frozen(self, node: str) -> float | None:
        until = self.paused.get(node)
        return until if until is not None and until > now() else None

    def send(self, src: str, dest: str, body) -> None:
        if dest not in self.nodes:
            raise ValueError(f"{src} sent a message to {dest!r}, which does not exist")
        msg = Message(src, dest, dict(body), next(self._ids))
        extra = self.sim.sending(msg)  # may start an incident; > 0 holds a write in the network
        until = self.frozen(src)
        if until is not None:  # a frozen process sends nothing until it wakes
            asyncio.get_running_loop().call_at(until, self._go, msg, extra)
        else:
            self._go(msg, extra)

    def _go(self, msg: Message, extra: float = 0.0) -> None:
        rec = Delivery(now(), msg.src, msg.dest, str(msg.body.get("type", "")))
        self.sim.left(msg, rec)
        if self.cut(msg.src, msg.dest):
            rec.dropped = True
            self.sim.done(msg, rec)
            return
        delay = self.latency * (1 + self.jitter * (2 * self.rng.random() - 1)) + extra
        asyncio.get_running_loop().call_later(delay, self._arrive, msg, rec)

    def _arrive(self, msg: Message, rec: Delivery) -> None:
        if self.cut(msg.src, msg.dest):
            rec.dropped = True
            self.sim.done(msg, rec)
            return
        until = self.frozen(msg.dest)
        if until is not None:  # it waits at a frozen process until it wakes
            asyncio.get_running_loop().call_at(until, self._arrive, msg, rec)
            return
        rec.arrived = now()
        self.sim.done(msg, rec)
        self.sim.arrived(msg)
        self.nodes[msg.dest]._deliver(msg)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.net = _Net(self, seed)
        self.ids = list(IDS)
        self.index = {n: i for i, n in enumerate(IDS)}
        self.client = Client("c1")
        self.net.join(self.client)
        self.nodes: dict[str, object] = {}
        self.planned: list[Planned] = []
        self.armed: Planned | None = None  # an incident waiting for its moment
        self.until: float | None = None  # when the incident going on ends
        self.victims: dict[float, int] = {}  # incident start -> the worker it hit
        self.sick: set[str] = set()  # the load balancer avoids them
        self.jobs: list[tuple] = []  # (start, job, worker, end, ok)
        # (sent, worker, left, arrived, accepted, stale, job, part, grant)
        self.writes: list[tuple] = []
        self.msgs: list[tuple] = []  # (sent, src, dest, arrived or None if dropped, kind)
        self.grants: list[tuple] = []  # (time, job, worker, grant number)
        self.releases: list[tuple] = []  # (time, job): a release reached the lock service
        self.granted: dict = {}  # job -> its latest grant number
        self.newest = 0  # the newest grant number among accepted writes
        self.seq = 0
        self._asks: dict[tuple[str, int], object] = {}  # (worker, msg_id) -> job, for acquire
        self._writes: dict[tuple[str, int], list] = {}  # (worker, msg_id) -> [job, part, sent, left, arrived]
        self._job_ids = itertools.count(1)

    # ---- the nodes

    def make(self, name: str):
        cls = {"lock": self.code.LockService, "storage": self.code.Storage}.get(name, self.code.Worker)
        node = cls(name, self.ids)
        self.net.join(node)
        self.nodes[name] = node
        return node

    async def setup(self) -> None:
        for name in self.ids:
            self.make(name)

    # ---- what the network sees

    def sending(self, msg: Message) -> float:
        """A message is handed to the network: note grants and writes; maybe start an incident."""
        body, kind = msg.body, msg.body.get("type")
        if msg.src in self.index and msg.src not in ("lock", "storage"):
            if kind == "acquire":
                self._asks[(msg.src, body.get("msg_id"))] = body.get("job")
            elif kind == "write":
                self._writes[(msg.src, body.get("msg_id"))] = [body.get("job"), body.get("part"), now(), None, None]
                return self._strike(msg.src)
        elif msg.src == "lock" and kind in ("acquire_ok", "error"):
            job = self._asks.pop((msg.dest, body.get("in_reply_to")), None)
            if kind == "acquire_ok" and job is not None:
                self.seq += 1
                self.granted[job] = self.seq
                self.grants.append((now(), job, self.index[msg.dest], self.seq))
        elif msg.src == "storage" and msg.dest in self.index:
            w = self._writes.pop((msg.dest, body.get("in_reply_to")), None)
            if w is not None:
                job, part, sent, left, arrived = w
                grant = self.granted.get(job, 0)
                accepted = kind == "write_ok"
                stale = grant < self.newest
                if accepted and not stale:
                    self.newest = grant
                self.writes.append((sent, self.index[msg.dest], left if left is not None else sent,
                                    arrived if arrived is not None else now(), accepted, stale, job, part, grant))
        return 0.0

    def _strike(self, worker: str) -> float:
        """An armed pause, delay or partition hits the worker that writes next."""
        inc = self.armed
        if inc is None or inc.kind == "crash":
            return 0.0
        end = self._hit(inc, worker)
        if inc.kind == "delay":
            return end - now()
        self.sick.add(worker)
        if inc.kind == "pause":
            self.net.paused[worker] = end
        else:
            self.net.cut_off.add(worker)
        return 0.0

    def _hit(self, inc: Planned, worker: str) -> float:
        """The incident starts now, on this worker, for as long as planned; returns when it ends."""
        self.armed = None
        t0 = round(now(), 2)
        hit = Planned(t0, round(t0 + inc.t1 - inc.t0, 2), inc.kind, inc.severity, inc.cause)
        self.planned.append(hit)
        self.victims[hit.t0] = self.index[worker]
        self.until = hit.t1
        return hit.t1

    def left(self, msg: Message, rec: Delivery) -> None:
        if msg.body.get("type") == "write":
            w = self._writes.get((msg.src, msg.body.get("msg_id")))
            if w is not None:
                w[3] = rec.sent

    def arrived(self, msg: Message) -> None:
        body = msg.body
        if msg.dest == "storage" and body.get("type") == "write":
            w = self._writes.get((msg.src, body.get("msg_id")))
            if w is not None:
                w[4] = now()
        elif msg.dest == "lock" and body.get("type") == "release":
            self.releases.append((now(), body.get("job")))
        elif body.get("type") == "acquire_ok" and msg.dest in self.index:
            inc = self.armed
            if inc is not None and inc.kind == "crash":  # it dies holding the lock
                self._hit(inc, msg.dest)
                self.crash(msg.dest)

    def done(self, msg: Message, rec: Delivery) -> None:
        """A message between nodes arrived or was dropped (writes are in their own table)."""
        if msg.src not in self.index or msg.dest not in self.index or msg.body.get("type") == "write":
            return
        kind = WRITE_REPLY if msg.src == "storage" else LOCK_MSG
        self.msgs.append((rec.sent, self.index[msg.src], self.index[msg.dest], rec.arrived, kind))

    # ---- incidents

    def crash(self, worker: str) -> None:
        self.net.down.add(worker)
        self.sick.add(worker)
        self.nodes[worker].net = _Void()  # its tasks may run on, but nothing they send goes anywhere

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            await asyncio.sleep(inc.t0 - now())
            self.armed, self.until = inc, None
            while self.armed is not None and now() < inc.t0 + ARM_MAX:  # wait for its moment
                await asyncio.sleep(0.05)
            self.armed = None
            if self.until is None:
                continue  # no job took the lock or wrote in time: it never happened
            await asyncio.sleep(self.until - now())
            for worker in list(self.net.down):  # it restarts, empty
                self.net.down.discard(worker)
                self.make(worker)
            self.net.paused.clear()
            self.net.cut_off.clear()
            self.sick.clear()

    # ---- the clients

    async def job(self, worker: str) -> None:
        job, start = next(self._job_ids), now()
        try:
            reply = await self.client.rpc(worker, {"type": "job", "job": job}, timeout=JOB_DEADLINE)
            ok = reply.get("type") == "job_ok"
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the job failed
            ok = False
        self.jobs.append((start, job, self.index[worker], now(), ok))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        names = [IDS[i] for i in WORKERS]
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            healthy = [n for n in names if n not in self.sick] or names
            asyncio.ensure_future(self.job(rng.choice(healthy)))

    def bugs(self) -> list[BaseException]:
        return self.net.bugs


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 0.8) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for coro in (s.setup(), s.traffic(), s.chaos()):
        sim.spawn(coro)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.net.bugs:
                raise s.net.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "victims": {t0: v for t0, v in s.victims.items() if a <= t0 < b},
                "tables": {
                    # (start, job, worker, end, ok)
                    "jobs": _take(s.jobs, 0, a, b),
                    # (sent, worker, left, arrived, accepted, stale, job, part, grant)
                    "writes": _take(s.writes, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped, kind)
                    "msgs": _take(s.msgs, 0, a, b),
                    # (time, job, worker, grant number)
                    "grants": _take(s.grants, 0, a, b),
                    # (time, job)
                    "releases": _take(s.releases, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
