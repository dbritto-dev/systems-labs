"""Lab graceful_shutdown: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (Poisson, drifting slowly like real traffic) to a fleet of 6
instances behind a load balancer (3 load balancer nodes; DNS spreads users over them). The
balancer passes connections through (layer 4, like a Kubernetes Service or a network load
balancer): it picks an instance, round robin, only when a client opens a new connection.
60% of requests come from clients that keep their connection open (keep-alive) and send
request after request on it, to the same instance, until they close it (after 10-30 s) or
the server does; the rest open a new connection each time. Users also keep ~100 streams
open (WebSockets, server-sent events) for minutes.

Each balancer node checks each instance's readiness every 2 s, each at its own moment. An
instance leaves a node's rotation after 3 failed checks in a row (a 503, or a refused
connection), and joins it after 2 good ones; the node needs 1 s more to apply either. A
request sent to an instance that is not listening is refused: the user gets an error.

Incidents come at random, like in production: a rolling deploy replaces all 6 instances
one by one (the orchestrator sends the old one SIGTERM and starts the new one, which boots
in 4 s; when it is ready, the next old one gets SIGTERM), a node is drained (a kernel patch,
a node upgrade, a spot instance reclaimed with a 2-minute notice: one instance is replaced),
or the autoscaler scales in by one (and back out 15 s later). Your `on_sigterm(server)`
decides what an instance does when it gets SIGTERM; 30 s later it is killed (SIGKILL)
whatever it is doing. The first incident is always a rolling deploy at 0:20. The run never
restarts: connections, streams and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import math
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now

LAB = "graceful_shutdown"
NAMES = ("on_sigterm", "drain", "shutdown")
PIECE = 60.0
DRAIN = 35.0  # simulate this far past a minute before handing it out (a SIGTERM ends within 30 s)
SAMPLE = 0.1  # how often the fleet's state is recorded

INSTANCES = 6
LB_NODES = 3
INTERVAL = 2.0  # seconds between two readiness checks of one instance by one balancer node
UNHEALTHY = 3  # failed checks in a row that take an instance out of a node's rotation
HEALTHY = 2  # good checks in a row that put it in
DEREGISTRATION = 1.0  # seconds a node takes to apply a change to its rotation
GRACE = 30.0  # SIGTERM to SIGKILL (Kubernetes' terminationGracePeriodSeconds)
BOOT = 4.0  # seconds a new instance takes to start and pass its readiness check

KEEPALIVE = 0.6  # share of requests sent on a kept-alive connection
CLIENTS = 150  # clients that keep a connection open
CONN_AGE = (10.0, 30.0)  # a client closes its connection after this long and opens a new one
SLOW_SHARE = 0.03  # share of requests that are slow (a report, an upload): 0.8-5 s
LONGEST = 6.0  # no request takes longer than this
STREAM_RATE = 1.0  # streams opened per second
STREAM_LIFE = 90.0  # median seconds a stream stays open
GOODBYE = (0.05, 0.5)  # a stream asked to reconnect closes within this many seconds
POLL = 0.05  # how often drained() looks at what is in flight

# Outcomes of a request or a stream.
OK, MOVED, CUT, REFUSED = range(4)
# What an instance slot shows: nothing, starting, serving, leaving (SIGTERM, still in rotation and serving),
# draining (SIGTERM, out of rotation, finishing its work), refusing (the balancer still sends it new
# connections but it does not listen: closed, or dead).
GONE, STARTING, SERVING, LEAVING, DRAINING, REFUSING = range(6)

# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
STEPS_DEPLOY = INSTANCES
LAST_STEP = (STEPS_DEPLOY - 1) * BOOT  # the last old instance gets SIGTERM this long after the start
AFTER_LAST = 10.0  # an incident ends this long after its last SIGTERM (the balancer has caught up)
FIRST = Planned(20.0, 20.0 + LAST_STEP + AFTER_LAST, "deploy", float(STEPS_DEPLOY), "release")
KINDS = [
    Kind("deploy", 0.5, median=LAST_STEP + AFTER_LAST, shortest=LAST_STEP + AFTER_LAST,
         longest=LAST_STEP + AFTER_LAST, severity=(STEPS_DEPLOY, STEPS_DEPLOY), causes=(
             "release", "config_change", "base_image", "rollback")),
    Kind("drain", 0.3, median=AFTER_LAST, shortest=AFTER_LAST, longest=AFTER_LAST, causes=(
        "kernel_patch", "node_upgrade", "spot_reclaim")),
    Kind("scale_in", 0.2, median=AFTER_LAST, shortest=AFTER_LAST, longest=AFTER_LAST, causes=(
        "traffic_dip", "night_schedule")),
]
MEAN_GAP = 25.0
QUIET = 40.0  # at least this calm after an incident: the last kill (≤ 20 s) + a 15 s baseline
SCALE_OUT = 5.0  # after a scale-in incident ends, the autoscaler adds an instance back this much later


def _s(key: str, **values) -> str:
    """One of the lab's STRINGS in the language in use (errors your code may see)."""
    return lab_text(LAB).STRINGS[key].format(**values)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def hit_slots(seed: int) -> Iterator[int]:
    """Where each incident starts: the first slot a deploy replaces, or the one instance it stops."""
    rng = random.Random(seed * 7 + 3)
    yield 0
    while True:
        yield rng.randrange(INSTANCES)


class Server:
    """One instance of the app, as your on_sigterm(server) sees it.

    For you:
      server.fail_readiness()   the readiness check (GET /ready) answers 503 from now on
      server.stop_accepting()   close the listening socket: new connections are refused
      server.close_idle()       close idle kept-alive connections, answer every later request with
                                "Connection: close", and ask streams to reconnect (a close frame)
      await server.drained(timeout=None)
                                wait until nothing is in flight (True), or `timeout` seconds (False)
      server.in_flight          requests and streams in flight now
      server.exit()             the process exits: whatever is still in flight is cut
      server.health_interval, server.unhealthy_threshold, server.deregistration_delay, server.grace
    """

    health_interval = INTERVAL
    unhealthy_threshold = UNHEALTHY
    deregistration_delay = DEREGISTRATION
    grace = GRACE

    def __init__(self, sim: "_Sim", iid: int, slot: int, born: float, booted: bool = False) -> None:
        self._sim = sim
        self.iid, self.slot = iid, slot
        self.booted_at = born if booted else born + BOOT
        self.ready = True  # what its readiness check answers (once booted)
        self.accepting = True  # its listening socket is open
        self.goaway = False  # close_idle() was called
        self.alive = True
        self.killed = False
        self.sigterm_at: float | None = None
        self.exit_at: float | None = None
        self.routed = [booted] * LB_NODES  # in each balancer node's rotation
        self.cut = 0
        self._requests: list[tuple[float, int, list]] = []  # (end, id, row): requests in flight (a heap)
        self._streams: dict[int, list] = {}  # id -> [start, end, lb node, moved]
        self._stream_ends: list[tuple[float, int]] = []  # (end, id), a heap; stale entries are skipped

    def __repr__(self) -> str:
        return f"<instance s{self.slot} #{self.iid}>"

    # ---- for your code

    def fail_readiness(self) -> None:
        self.ready = False

    def stop_accepting(self) -> None:
        self.accepting = False

    def close_idle(self) -> None:
        if not self.alive or self.goaway:
            return
        self.goaway = True
        t = now()
        rng = self._sim.rng
        for sid, s in self._streams.items():
            if not s[3]:
                s[3] = True
                s[1] = min(s[1], t + rng.uniform(*GOODBYE))
                heapq.heappush(self._stream_ends, (s[1], sid))

    @property
    def in_flight(self) -> int:
        self.settle(now())
        return len(self._requests) + len(self._streams)

    async def drained(self, timeout: float | None = None) -> bool:
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))):
            raise TypeError(_s("bad_timeout", value=repr(timeout)))
        end = math.inf if timeout is None else now() + max(0.0, timeout)
        while self.alive and self.in_flight:
            if now() >= end:
                return False
            await asyncio.sleep(min(POLL, end - now()))
        return True

    def exit(self) -> None:
        if self.alive:
            self._sim.gone(self, now(), killed=False)

    # ---- for the scenario

    def listening(self, t: float) -> bool:
        return self.alive and self.accepting and t >= self.booted_at

    def healthy(self, t: float) -> bool:
        return self.listening(t) and self.ready

    def serve(self, row: list, t: float, duration: float) -> None:
        row[2] = t + duration
        heapq.heappush(self._requests, (row[2], row[0], row))

    def open_stream(self, sid: int, t: float, life: float, lb: int) -> None:
        self._streams[sid] = [t, t + life, lb, False]
        heapq.heappush(self._stream_ends, (t + life, sid))

    def settle(self, t: float) -> None:
        """Requests and streams that have ended by t leave."""
        reqs = self._requests
        while reqs and reqs[0][0] <= t:
            heapq.heappop(reqs)
        ends = self._stream_ends
        while ends and ends[0][0] <= t:
            end, sid = heapq.heappop(ends)
            s = self._streams.get(sid)
            if s is None or s[1] != end:
                continue  # stale: it was moved earlier
            del self._streams[sid]
            self._sim.stream_ended(sid, s, self, end, MOVED if s[3] else OK)

    def cut_everything(self, t: float) -> None:
        self.settle(t)
        for _, _, row in self._requests:
            row[2], row[3], row[4] = t, False, CUT
        self.cut += len(self._requests)
        self._requests.clear()
        for sid, s in self._streams.items():
            self._sim.stream_ended(sid, s, self, t, CUT)
        self.cut += len(self._streams)
        self._streams.clear()
        self._stream_ends.clear()

    def state(self, t: float) -> int:
        routed = any(self.routed)
        if not self.alive:
            return REFUSING if routed else GONE
        if self.sigterm_at is not None:
            if routed:
                return LEAVING if self.accepting else REFUSING
            return DRAINING
        if t < self.booted_at or not routed:
            return STARTING
        return SERVING


class _Sim:
    def __init__(self, code, seed: int, rate: float, loop: asyncio.AbstractEventLoop) -> None:
        self.code, self.seed, self.rate, self.loop = code, seed, rate, loop
        self.rng = random.Random(seed * 7 + 1)
        self.ids = itertools.count()
        self.iids = itertools.count()
        self.sids = itertools.count()
        self.current: list[Server | None] = [None] * INSTANCES  # the instance each slot runs
        self.old: list[Server | None] = [None] * INSTANCES  # one still shutting down in that slot
        self.rotation: list[list[Server]] = [[] for _ in range(LB_NODES)]  # each node's instances
        self.turn = [0] * LB_NODES  # round robin, per node
        self.conn: list[Server | None] = [None] * CLIENTS  # each client's kept-alive connection
        self.conn_lb = [0] * CLIENTS
        self.conn_until = [0.0] * CLIENTS
        self.requests: list[list] = []  # [id, start, end, ok, outcome, slot, lb node, kept alive, to an old one]
        self.streams: list[tuple] = []  # (end, start, slot, outcome, lb node, id)
        self.instances: list[tuple] = []  # (sigterm, exit, slot, killed, cut, id)
        self.samples: list[tuple] = []  # (t, state per slot, serving, in flight per slot)
        self.hits: list[tuple] = []  # (t0, t1, slot): where each incident starts
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        for slot in range(INSTANCES):
            self.start(slot, 0.0, booted=True)

    # ---- the fleet

    def start(self, slot: int, t: float, booted: bool = False) -> Server:
        inst = Server(self, next(self.iids), slot, t, booted)
        self.current[slot] = inst
        if booted:
            for n in range(LB_NODES):
                self.rotation[n].append(inst)
        for n in range(LB_NODES):
            self.loop.create_task(self.checks(inst, n))
        return inst

    def sigterm(self, slot: int, t: float) -> None:
        inst = self.current[slot]
        if inst is None:
            return
        self.current[slot] = None
        self.old[slot] = inst
        inst.sigterm_at = t
        task = self.loop.create_task(self.handler(inst))
        self.loop.call_at(t + GRACE, self.kill, inst, task)

    async def handler(self, inst: Server) -> None:
        try:
            await self.code.on_sigterm(inst)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
        if inst.alive:  # on_sigterm returned: the process exits
            self.gone(inst, now(), killed=False)

    def kill(self, inst: Server, task: asyncio.Task) -> None:
        if inst.alive:
            self.gone(inst, now(), killed=True)
            task.cancel()

    def gone(self, inst: Server, t: float, killed: bool) -> None:
        """The process exits (or is killed): whatever is in flight is cut."""
        inst.cut_everything(t)
        inst.alive = inst.accepting = False
        inst.killed, inst.exit_at = killed, t
        if inst.sigterm_at is not None:
            self.instances.append((inst.sigterm_at, t, inst.slot, killed, inst.cut, inst.iid))

    async def checks(self, inst: Server, n: int) -> None:
        """Balancer node n checks inst's readiness every INTERVAL seconds, at its own moment."""
        await asyncio.sleep(self.rng.uniform(0.0, INTERVAL))
        good = bad = 0
        want = inst.routed[n]
        while inst.alive or inst.routed[n]:
            if inst.healthy(now()):
                good, bad = good + 1, 0
            else:
                good, bad = 0, bad + 1
            if not want and good >= HEALTHY:
                want = True
                self.loop.call_later(DEREGISTRATION, self.route, inst, n, True)
            elif want and bad >= UNHEALTHY:
                want = False
                self.loop.call_later(DEREGISTRATION, self.route, inst, n, False)
            await asyncio.sleep(INTERVAL)

    def route(self, inst: Server, n: int, on: bool) -> None:
        if inst.routed[n] == on:
            return
        inst.routed[n] = on
        if on:
            self.rotation[n].append(inst)
        else:
            self.rotation[n].remove(inst)

    def pick(self, n: int) -> Server | None:
        """Balancer node n picks an instance for a new connection: round robin over its rotation."""
        rot = self.rotation[n]
        if not rot:
            return None
        self.turn[n] += 1
        return rot[self.turn[n] % len(rot)]

    # ---- traffic

    def duration(self) -> float:
        rng = self.rng
        if rng.random() < SLOW_SHARE:
            return rng.uniform(0.8, 5.0)
        return min(1.0, rng.lognormvariate(math.log(0.06), 0.6))

    def request(self, t: float) -> None:
        rng = self.rng
        rid = next(self.ids)
        kept = rng.random() < KEEPALIVE
        c = rng.randrange(CLIENTS) if kept else -1
        inst = self.conn[c] if kept else None
        if inst is not None and inst.alive and not inst.goaway and t < self.conn_until[c]:
            n = self.conn_lb[c]  # an open connection: it goes to the same instance, whatever the balancer knows
        else:
            n = rid % LB_NODES
            inst = self.pick(n)
            if kept:
                self.conn[c] = None
            if inst is None or not inst.listening(t):  # refused: nobody listens there
                self.requests.append([rid, t, t + 0.001, False, REFUSED, inst.slot if inst else -1, n, kept,
                                      inst is not None and inst.sigterm_at is not None])
                return
            if kept:
                self.conn[c], self.conn_lb[c], self.conn_until[c] = inst, n, t + rng.uniform(*CONN_AGE)
        row = [rid, t, t, True, OK, inst.slot, n, kept, inst.sigterm_at is not None]
        inst.serve(row, t, self.duration())
        self.requests.append(row)

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            self.request(now())

    def open_stream(self, t: float, tries: int = 0) -> None:
        sid = next(self.sids)
        n = sid % LB_NODES
        inst = self.pick(n)
        if inst is None or not inst.listening(t):
            self.streams.append((t, t, inst.slot if inst else -1, REFUSED, n, sid))
            if tries < 2:  # the client tries again a little later
                self.loop.call_later(self.rng.uniform(1.0, 2.0), self.reopen, tries + 1)
            return
        inst.open_stream(sid, t, self.rng.lognormvariate(math.log(STREAM_LIFE), 0.6), n)

    def reopen(self, tries: int = 0) -> None:
        self.open_stream(now(), tries)

    def stream_ended(self, sid: int, s: list, inst: Server, t: float, outcome: int) -> None:
        self.streams.append((t, s[0], inst.slot, outcome, s[2], sid))
        if outcome == MOVED:  # asked to reconnect: it does, through the balancer
            self.loop.call_at(t + 0.2, self.reopen)
        elif outcome == CUT:  # the connection dropped: the client notices and reconnects
            self.loop.call_at(t + self.rng.uniform(1.0, 3.0), self.reopen)

    async def stream_traffic(self) -> None:
        rng = random.Random(self.seed * 7 + 5)
        # Start with the streams a long-running fleet has open.
        for _ in range(round(STREAM_RATE * STREAM_LIFE * 1.2)):
            sid = next(self.sids)
            n = sid % LB_NODES
            inst = self.pick(n)
            inst.open_stream(sid, 0.0, rng.uniform(0.0, 2.4 * STREAM_LIFE), n)
        while True:
            await asyncio.sleep(rng.expovariate(STREAM_RATE))
            self.open_stream(now())

    # ---- incidents

    async def chaos(self) -> None:
        where = hit_slots(self.seed)
        for inc in incidents(self.seed):
            self.planned.append(inc)
            first = next(where)
            self.hits.append((inc.t0, inc.t1, first))
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "deploy":
                for k in range(STEPS_DEPLOY):  # one by one: the next when the new one is ready
                    slot = (first + k) % INSTANCES
                    self.sigterm(slot, now())
                    self.start(slot, now())
                    if k < STEPS_DEPLOY - 1:
                        await asyncio.sleep(BOOT)
            elif inc.kind == "drain":  # the node is drained: its instance is started on another node
                self.sigterm(first, now())
                self.start(first, now())
            else:  # scale in by one; the autoscaler adds one back later
                self.sigterm(first, now())
                await asyncio.sleep(inc.t1 + SCALE_OUT - now())
                self.start(first, now())

    async def sampler(self) -> None:
        while True:
            t = now()
            states, flying = [], []
            serving = 0
            for slot in range(INSTANCES):
                for inst in (self.old[slot], self.current[slot]):
                    if inst is not None:
                        inst.settle(t)
                        serving += inst.listening(t) and any(inst.routed)
                old = self.old[slot]
                if old is not None and not old.alive and not any(old.routed):
                    self.old[slot] = old = None
                shown = old or self.current[slot]
                states.append(shown.state(t) if shown else GONE)
                flying.append(len(shown._requests) + len(shown._streams) if shown and shown.alive else 0)
            self.samples.append((round(t, 3), tuple(states), serving, tuple(flying)))
            await asyncio.sleep(SAMPLE)

    @staticmethod
    def take(rows: list, col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted, as tuples."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [tuple(r) for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 300.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate, sim.loop)
    for task in (s.traffic(), s.stream_traffic(), s.chaos(), s.sampler()):
        sim.spawn(task)
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
                    "requests": s.take(s.requests, 1, a, b),
                    "streams": s.take(s.streams, 0, a, b),
                    "instances": s.take(s.instances, 0, a, b),
                    "samples": s.take(s.samples, 0, a, b),
                    "hits": s.take(s.hits, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 300.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
