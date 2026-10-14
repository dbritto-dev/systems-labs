"""Lab quorum: leaderless replication (Dynamo-style), one endless run on virtual time.

5 nodes on a simulated network (~100 ms per message). Every key lives on 3 of them (its
replicas: `replicas_for(key, node_ids)`). Clients send `put` and `get` to any healthy node,
which coordinates: it talks to the key's replicas and answers the client.

Incidents, like in production: a node crashes (its disk survives, so it comes back with old
data), a node is cut off by the network, or a node gets very slow. The load balancer stops
sending clients to a sick node, but it is still a replica for 3/5 of the keys. The first
incident always crashes n2 at 0:20-0:30.

The checker looks inside the nodes (their `store`), outside the network, to see whether a
key's replicas agree. Clients never write the same key twice at once.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Network
from core.vtime import VirtualRun, now

LAB = "quorum"
NAMES = ("QuorumNode",)
PIECE = 60.0
DRAIN = 15.0
NODES = 5
KEYS = 200
CLIENT_TIMEOUT = 1.0
CHECK_EVERY = 0.25  # how often the checker compares the replicas
SETTLED = 1.0  # a key whose last write started this recently is still settling
SLOW_FACTOR = 8.0  # a slow node's messages take this many times longer
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "crash", 1.0, "oom_kill")
KINDS = [
    Kind("crash", 0.45, median=10.0, shortest=5.0, longest=25.0, causes=(
        "oom_kill", "kernel_panic", "bad_deploy")),
    Kind("isolate", 0.3, median=8.0, shortest=4.0, longest=20.0, causes=(
        "switch_port", "firewall_rule", "dns")),
    Kind("slow", 0.25, median=12.0, shortest=6.0, longest=25.0, causes=(
        "gc_pause", "disk_full", "noisy_neighbour")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # calm after an incident: 10 s to judge convergence, 15 s of baseline before the next

# Operation kinds.
PUT, GET = 0, 1


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, seed: int) -> int:
    """Which node the incident hits (the first one always hits n2)."""
    if inc.t0 == FIRST.t0:
        return 2
    return random.Random(f"{seed}:{inc.t0}:victim").randrange(NODES)


def replicas_for(key: str, node_ids: list[str], n: int = 3) -> list[str]:
    """The n nodes that hold `key`: its home node and the next ones round the ring."""
    home = int(key[1:]) % len(node_ids)
    return [node_ids[(home + j) % len(node_ids)] for j in range(n)]


class _Net(Network):
    """The simulated network, plus what happens to one sick node."""

    def __init__(self, seed: int) -> None:
        super().__init__(latency=0.1, jitter=0.2, seed=seed)
        self.down: set[str] = set()  # crashed or cut off: nothing gets in or out
        self.slow: str | None = None

    def cut(self, a: str, b: str) -> bool:
        return a in self.down or b in self.down or super().cut(a, b)

    def send(self, src: str, dest: str, body) -> None:
        if self.slow is not None and self.slow in (src, dest):
            saved = self.latency
            self.latency = saved * SLOW_FACTOR
            try:
                super().send(src, dest, body)
            finally:
                self.latency = saved
        else:
            super().send(src, dest, body)


def _value_of(entry):
    """What a node stores for a key, whatever shape it uses: (version, value) or a value."""
    if isinstance(entry, (tuple, list)) and entry:
        return entry[-1]
    return entry


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = _Net(seed)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.code = code
        self.nodes: list = []
        self.client = Client("c1")
        self.net.join(self.client)
        self.planned: list[Planned] = []
        self.sick: str | None = None  # the load balancer avoids it
        self.ops: list[tuple] = []  # (start, kind, node, key, value, end, ok, stale)
        self.written: dict[str, float] = {}  # key -> when its last write started
        self.acked: dict[str, list[tuple[float, int]]] = {}  # key -> [(ack time, value)]
        self.busy: set[str] = set()  # keys with a write in flight
        self.conv: list[tuple] = []  # (time, converged share, keys behind per node)
        self._value = itertools.count(1)

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.QuorumNode(n, self.ids)
            if not hasattr(node, "store"):
                raise AttributeError(lab_text(LAB).STRINGS["no_store"])
            self.net.join(node)
            self.nodes.append(node)

    def _expected(self, key: str, start: float) -> int | None:
        """The newest value acknowledged before `start` (what a read must return at least)."""
        best = None
        for t, v in self.acked.get(key, ()):
            if t < start and (best is None or v > best):
                best = v
        return best

    async def _op(self, kind: int, node: str, key: str, value: int = -1) -> None:
        start = now()
        body = {"type": "put", "key": key, "value": value} if kind == PUT else {"type": "get", "key": key}
        got, ok = None, False
        try:
            reply = await self.client.rpc(node, body, timeout=CLIENT_TIMEOUT)
            ok = True
            got = reply.get("value")
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the client gives up
            ok = False
        end = now()
        stale = False
        if kind == PUT:
            self.busy.discard(key)
            if ok:
                history = self.acked.setdefault(key, [])
                history.append((end, value))
                del history[:-4]
        elif ok:
            expected = self._expected(key, start)
            stale = expected is not None and (not isinstance(got, int) or got < expected)
            value = got if isinstance(got, int) else -1
        self.ops.append((start, kind, self.index[node], int(key[1:]), value, end, ok, stale))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            healthy = [n for n in self.ids if n != self.sick]
            node = rng.choice(healthy)
            key = f"k{rng.randrange(KEYS)}"
            if rng.random() < 0.5 and key not in self.busy:
                self.busy.add(key)
                self.written[key] = now()
                asyncio.ensure_future(self._op(PUT, node, key, next(self._value)))
            else:
                asyncio.ensure_future(self._op(GET, node, key))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            sick = self.ids[victim(inc, self.seed)]
            self.sick = sick
            if inc.kind == "slow":
                self.net.slow = sick
            else:
                self.net.down.add(sick)
            await asyncio.sleep(inc.t1 - now())
            self.net.down.discard(sick)
            self.net.slow = None
            self.sick = None

    async def checker(self) -> None:
        """Every 250 ms: do the replicas of each settled key hold the same value? (No traffic.)"""
        while True:
            await asyncio.sleep(CHECK_EVERY)
            t = now()
            behind = [0] * NODES
            total = agree = 0
            for key, started in self.written.items():
                if t - started < SETTLED or key in self.busy:
                    continue
                reps = replicas_for(key, self.ids)
                values = [_value_of(self.nodes[self.index[r]].store.get(key)) for r in reps]
                total += 1
                newest = max((v for v in values if isinstance(v, int)), default=None)
                if all(v == newest for v in values):
                    agree += 1
                else:
                    for r, v in zip(reps, values):
                        if v != newest:
                            behind[self.index[r]] += 1
            self.conv.append((t, agree / total if total else 1.0, tuple(behind)))

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between nodes sent in [a, b): (sent, src, dest, arrived or None)."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.src in self.index and d.dest in self.index and d.sent >= a:
                out.append((d.sent, self.index[d.src], self.index[d.dest], d.arrived))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 20.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for coro in (s.setup(), s.traffic(), s.chaos(), s.checker()):
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
                "victims": {i.t0: victim(i, seed) for i in s.planned if a <= i.t0 < b},
                "tables": {
                    # (start, kind, node, key, value, end, ok, stale)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped)
                    "msgs": s.messages(a, b),
                    # (time, converged share, keys behind per node)
                    "conv": _take(s.conv, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
