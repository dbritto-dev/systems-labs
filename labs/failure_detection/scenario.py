"""Lab failure_detection: who is dead? One endless run on virtual time.

8 nodes on a simulated network (~50 ms per message). Every node runs your `Detector` and keeps
`self.status`: what it thinks of every other node ("alive", "suspect" or "dead"). The cluster's
view is what its healthy nodes say: a node is out as soon as one of them declares it dead (a death
is news that spreads), suspected while one of them suspects it.

The network is never clean: four links run through an old switch with a failing optic and lose
half of their messages. On top of that, incidents come at
random, like in production: a node crashes (and restarts), a node gets slow (every message to or
from it takes several times longer), a node's links lose a share of the messages, or a firewall
rule cuts a node off from 2 or 3 of the others while the rest still reach it (a partial
partition). Only the crash should end with a death. The first incident always crashes n2 at
0:20-0:30. The cluster has been up for 30 s when the run starts at 0:00.

Clients are routed by the cluster's view: each session has a home node; when the view says it is
dead, the router fails it over to the next node (extra work); when the home node crashed but the
view has not noticed yet, the request fails.

The checker reads every node's `status` every 250 ms, outside the network. A node that has just
come back from a crash gets 3 s to rejoin before its view (and a death of it) counts.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Delivery, Message, Network
from core.vtime import VirtualRun, now as _now

LAB = "failure_detection"
NAMES = ("Detector",)
PIECE = 60.0
DRAIN = 5.0
NODES = 8
LATENCY = 0.05
CHECK_EVERY = 0.25  # how often the checker reads the nodes' views
WARMUP = 30.0  # the cluster has been up this long when the run starts at 0:00
JOIN = 3.0  # seconds a node that came back gets before its view (and its death) counts
CLIENT_TIMEOUT = 1.0
SERVE = 0.05  # seconds a node takes to answer a client
COLD = 0.2  # extra seconds when a session is failed over to a node that does not have it
FLAKY = ((0, 5), (1, 7), (3, 6), (4, 7))  # links through the old switch
FLAKY_LOSS = 0.5  # share of the messages they lose
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "crash", 1.0, "oom_kill")
KINDS = [
    Kind("crash", 0.35, median=10.0, shortest=5.0, longest=25.0, causes=(
        "oom_kill", "kernel_panic", "host_reboot", "bad_deploy")),
    Kind("slow", 0.25, median=12.0, shortest=6.0, longest=25.0, severity=(3.0, 5.0), causes=(
        "gc_pause", "noisy_neighbour", "disk_full")),
    Kind("lossy", 0.2, median=12.0, shortest=6.0, longest=25.0, severity=(0.15, 0.3), causes=(
        "bad_cable", "nic_firmware", "duplex_mismatch")),
    Kind("partial", 0.2, median=10.0, shortest=5.0, longest=20.0, severity=(2.0, 3.99), causes=(
        "firewall_rule", "stale_route", "security_group")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # calm after an incident: 5 s to judge it, 15 s of baseline before the next

# What a node thinks of another (the checker's codes), and what happened to a client request.
ALIVE, SUSPECT, DEAD = 0, 1, 2
MARKS = {"alive": ALIVE, "suspect": SUSPECT, "dead": DEAD}
SERVED, FAILED, FAILOVER, NEEDLESS = 0, 1, 2, 3


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, seed: int) -> int:
    """Which node the incident hits (the first one always hits n2)."""
    if inc.t0 == FIRST.t0:
        return 2
    return random.Random(f"{seed}:{inc.t0}:victim").randrange(NODES)


def cut_off(inc: Planned, seed: int) -> list[int]:
    """A partial partition: the nodes the victim cannot reach (2 or 3 of them)."""
    if inc.kind != "partial":
        return []
    v = victim(inc, seed)
    others = [i for i in range(NODES) if i != v]
    return sorted(random.Random(f"{seed}:{inc.t0}:cut").sample(others, int(inc.severity)))


def is_indirect(kind: str) -> bool:
    """Messages of an indirect probe (ping_req and its answer), for the picture."""
    return "req" in kind or "indirect" in kind


def now() -> float:
    """The lab's clock: the simulation runs WARMUP seconds before 0:00."""
    return _now() - WARMUP


class _Net(Network):
    """The simulated network: flaky links, and what an incident does to one node."""

    def __init__(self, seed: int) -> None:
        super().__init__(latency=LATENCY, jitter=0.2, seed=seed)
        self.seed = seed
        self.down: set[str] = set()  # crashed: nothing gets in or out
        self.slow: dict[str, float] = {}  # node -> how many times slower its messages are
        self.lossy: dict[str, float] = {}  # node -> share of its messages lost
        self.blocked: set[frozenset[str]] = set()  # pairs that cannot talk (a partial partition)
        self.losses = random.Random(seed * 13 + 7)
        self.flaky = {(f"n{a}", f"n{b}") for a, b in FLAKY} | {(f"n{b}", f"n{a}") for a, b in FLAKY}

    def cut(self, a: str, b: str) -> bool:
        return a in self.down or b in self.down or frozenset((a, b)) in self.blocked or super().cut(a, b)

    def send(self, src: str, dest: str, body) -> None:
        if dest not in self.nodes:
            raise ValueError(f"{src} sent a message to {dest!r}, which does not exist")
        msg = Message(src, dest, dict(body), next(self._ids))
        rec = Delivery(_now(), src, dest, str(body.get("type", "")))
        self.log.append(rec)
        loss = max(self.lossy.get(src, 0.0), self.lossy.get(dest, 0.0), FLAKY_LOSS if (src, dest) in self.flaky else 0.0)
        if self.cut(src, dest) or (loss and self.losses.random() < loss):
            rec.dropped = True
            return
        delay = self.latency * (1 + self.jitter * (2 * self.rng.random() - 1))
        delay *= max(self.slow.get(src, 1.0), self.slow.get(dest, 1.0))
        asyncio.get_running_loop().call_later(delay, self._arrive, msg, rec)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = _Net(seed)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.code = code
        self.nodes: list = []
        self.planned: list[Planned] = []
        self.up_since: list[float | None] = [-JOIN] * NODES  # None while crashed
        self.marks = [ALIVE] * NODES  # the cluster's view, as of the last check
        self.prev: dict[tuple[int, int], int] = {}  # (observer, peer) -> its last mark
        self.counted: set[int] = set()  # observers whose view counted at the last check
        self.views: list[tuple] = []  # (time, marks, crashed bitmask)
        self.deaths: list[tuple] = []  # (time, observer, peer, false)
        self.reqs: list[tuple] = []  # (start, home, node, end, outcome, ok)

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.Detector(n, self.ids)
            if not isinstance(getattr(node, "status", None), dict):
                raise AttributeError(lab_text(LAB).STRINGS["no_status"])
            self.net.join(node)
            self.nodes.append(node)

    def settled(self, i: int, t: float) -> bool:
        """Up, and long enough to have rejoined."""
        since = self.up_since[i]
        return since is not None and t - since >= JOIN

    async def checker(self) -> None:
        """Every 250 ms: what does each node think of the others? (No traffic.)"""
        while True:
            await asyncio.sleep(CHECK_EVERY)
            t = now()
            if t < 0:
                continue  # still warming up
            marks = [ALIVE] * NODES
            counted = set()
            for o, node in enumerate(self.nodes):
                counts = self.settled(o, t)
                if counts:
                    counted.add(o)
                status = getattr(node, "status", {})
                for p, j in self.index.items():
                    if j == o:
                        continue
                    m = MARKS.get(status.get(p), ALIVE) if isinstance(status, dict) else ALIVE
                    before = self.prev.get((o, j), ALIVE)
                    self.prev[(o, j)] = m
                    if not counts:
                        continue
                    marks[j] = max(marks[j], m)
                    if m == DEAD and before != DEAD and o in self.counted:
                        if self.up_since[j] is None:
                            self.deaths.append((t, o, j, False))
                        elif self.settled(j, t):
                            self.deaths.append((t, o, j, True))  # a healthy node declared dead
            self.counted = counted
            self.marks = marks
            crashed = sum(1 << i for i, s in enumerate(self.up_since) if s is None)
            self.views.append((t, tuple(marks), crashed))

    async def chaos(self) -> None:
        net = self.net
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            v = victim(inc, self.seed)
            n = self.ids[v]
            cut = [frozenset((n, self.ids[j])) for j in cut_off(inc, self.seed)]
            if inc.kind == "crash":
                net.down.add(n)
                self.up_since[v] = None
            elif inc.kind == "slow":
                net.slow[n] = inc.severity
            elif inc.kind == "lossy":
                net.lossy[n] = inc.severity
            else:
                net.blocked.update(cut)
            await asyncio.sleep(inc.t1 - now())
            if inc.kind == "crash":
                net.down.discard(n)
                self.up_since[v] = now()
            net.slow.pop(n, None)
            net.lossy.pop(n, None)
            net.blocked.difference_update(cut)

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.request(rng.randrange(NODES)))

    async def request(self, home: int) -> None:
        """One client request, routed by the cluster's view: its home node, or the next one it thinks alive."""
        start = now()
        node = next((j % NODES for j in range(home, home + NODES) if self.marks[j % NODES] != DEAD), home)
        moved = node != home
        if self.up_since[node] is None:
            await asyncio.sleep(CLIENT_TIMEOUT)
            outcome = FAILED
        else:
            serve = SERVE * self.net.slow.get(self.ids[node], 1.0) + (COLD if moved else 0.0)
            await asyncio.sleep(serve)
            if self.up_since[node] is None:  # it crashed while serving
                await asyncio.sleep(CLIENT_TIMEOUT - serve)
                outcome = FAILED
            elif moved:
                outcome = NEEDLESS if self.settled(home, start) else FAILOVER  # moved off a healthy node?
            else:
                outcome = SERVED
        self.reqs.append((start, home, node, now(), outcome, outcome != FAILED))

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between nodes sent in [a, b): (sent, src, dest, arrived or None, indirect)."""
        out, keep = [], []
        for d in self.net.log:
            sent = d.sent - WARMUP
            if sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.src in self.index and d.dest in self.index and sent >= a:
                arrived = None if d.arrived is None else d.arrived - WARMUP
                out.append((sent, self.index[d.src], self.index[d.dest], arrived, is_indirect(d.type)))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 30.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for coro in (s.setup(), s.checker(), s.chaos(), s.traffic()):
        sim.spawn(coro)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(WARMUP + b + DRAIN)
            if s.net.bugs:
                raise s.net.bugs[0]
            mine = [i for i in s.planned if a <= i.t0 < b]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in mine],
                "victims": {i.t0: victim(i, seed) for i in mine},
                "cut": {i.t0: cut_off(i, seed) for i in mine},
                "tables": {
                    # (sent, src, dest, arrived or None if dropped, indirect)
                    "msgs": s.messages(a, b),
                    # (time, the cluster's mark of each node, crashed nodes as a bitmask)
                    "views": _take(s.views, 0, a, b),
                    # (time, observer, peer, false): a node declared dead (false: it was healthy)
                    "deaths": _take(s.deaths, 0, a, b),
                    # (start, home, node, end, outcome, ok: not FAILED)
                    "reqs": _take(s.reqs, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
