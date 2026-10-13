"""Lab broadcast (Fly.io Gossip Glomers #3): one endless run on virtual time.

25 nodes on a simulated network (100 ms per message). Clients send ~`rate` operations/s
to random nodes: half `broadcast` (a new unique number), half `read` (every number the
node has). Your `BroadcastNode` must get every number to every node.

Incidents are network partitions, like in production: the cluster splits in two (a
switch failed, a zone lost its link), or one node is cut off. The first one always splits
the cluster in half at 0:20-0:30.

The checker looks at each node's `messages` set every 20 ms, outside the network (not
counted as traffic), to see when each number has reached every node.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Network, Topology
from core.vtime import VirtualRun, now

LAB = "broadcast"
NAMES = ("BroadcastNode",)
PIECE = 60.0
DRAIN = 20.0
SIDE = 5  # a 5 x 5 grid of nodes
PROBE = 0.02  # how often the checker looks at every node
LAG_EVERY = 0.1  # how often each node's backlog is recorded for the picture
CLIENT_TIMEOUT = 1.0
GIVE_UP = 30.0  # a number not everywhere after this long is recorded as lost
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "split", 0.5, "tor_switch")
KINDS = [
    Kind("split", 0.6, median=10.0, shortest=5.0, longest=25.0, severity=(0.3, 0.5), causes=(
        "tor_switch", "zone_link", "bgp_flap")),
    Kind("isolate", 0.4, median=8.0, shortest=4.0, longest=20.0, causes=(
        "firewall_rule", "bad_nic", "security_group")),
]
MEAN_GAP = 30.0
QUIET = 27.0  # calm before the next one: 15 s measured before it, 7 s to judge the last

# Operation kinds.
BROADCAST, READ = 0, 1


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def groups_for(inc: Planned, ids: list[str], seed: int) -> list[set[str]]:
    """Which nodes can still talk to each other during the incident (a cut through the grid)."""
    rng = random.Random(hash((seed, inc.t0)) & 0xFFFFFFFF)
    if inc.kind == "isolate":
        alone = rng.choice(ids)
        return [{alone}, set(ids) - {alone}]
    cut = max(1, round(SIDE * inc.severity))  # columns (or rows) on the small side
    by_rows = rng.random() < 0.5
    small = {n for i, n in enumerate(ids) if (i // SIDE if by_rows else i % SIDE) < cut}
    return [small, set(ids) - small]


class _Sim:
    def __init__(self, code, seed: int, rate: float, nodes: int) -> None:
        self.seed, self.rate = seed, rate
        self.net = Network(latency=0.1, jitter=0.2, seed=seed)
        self.ids = [f"n{i}" for i in range(nodes)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.code = code
        self.nodes: list = []  # built in setup(), inside the simulation (they may start timers)
        self.client = Client("c1")
        self.net.join(self.client)
        self.topology = Topology.grid(self.ids).neighbours
        self.planned: list[Planned] = []
        self.ops: list[tuple] = []  # finished: (start, kind, node, value, end, ok)
        self.open_ops: dict[int, float] = {}
        self.sent: dict[int, float] = {}  # value -> when the client sent it
        self.pending: dict[int, float] = {}  # values not yet on every node -> sent
        self.reached: list[tuple] = []  # (when every node had it, value)
        self.lost: list[tuple] = []  # (gave up at, value)
        self.lag: list[tuple] = []  # (time, (missing values per node...))
        self.groups: list[set[str]] | None = None
        self._seq = itertools.count()

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.BroadcastNode(n, self.ids)
            if not hasattr(node, "messages"):
                raise AttributeError(lab_text(LAB).STRINGS["no_messages"])
            self.net.join(node)
            self.nodes.append(node)
        for n in self.ids:  # like Maelstrom: tell every node its neighbours first
            asyncio.ensure_future(self._op(-1, n, {"type": "topology", "topology": self.topology}))

    async def _op(self, kind: int, node: str, body: dict, value: int = -1) -> None:
        k = next(self._seq)
        start = now()
        self.open_ops[k] = start
        try:
            await self.client.rpc(node, body, timeout=CLIENT_TIMEOUT)
            ok = True
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the client gives up
            ok = False
        finally:
            self.open_ops.pop(k, None)
        if kind >= 0:
            self.ops.append((start, kind, self.index[node], value, now(), ok))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7 + 1)
        value = 0
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            node = rng.choice(self.ids)
            if rng.random() < 0.5:
                value += 1
                self.sent[value] = self.pending[value] = now()
                asyncio.ensure_future(self._op(BROADCAST, node, {"type": "broadcast", "message": value}, value))
            else:
                asyncio.ensure_future(self._op(READ, node, {"type": "read"}))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            self.groups = groups_for(inc, self.ids, self.seed)
            self.net.partition(self.groups)
            await asyncio.sleep(inc.t1 - now())
            self.net.heal()
            self.groups = None

    async def checker(self) -> None:
        """Every 50 ms: which numbers has every node got? (Looks inside the nodes; sends nothing.)"""
        next_lag = 0.0
        while True:
            await asyncio.sleep(PROBE)
            t = now()
            for v, sent in list(self.pending.items()):
                if all(v in node.messages for node in self.nodes):
                    del self.pending[v]
                    self.reached.append((t, v))
                elif t - sent > GIVE_UP:
                    del self.pending[v]
                    self.lost.append((t, v))
            if t >= next_lag:
                next_lag = t + LAG_EVERY
                missing = tuple(sum(1 for v in self.pending if v not in node.messages) for node in self.nodes)
                self.lag.append((t, missing))

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between nodes sent in [a, b): (sent, src, dest, arrived or None)."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)  # later, or still on the wire
                continue
            if d.src in self.index and d.dest in self.index and d.sent >= a:
                out.append((d.sent, self.index[d.src], self.index[d.dest], d.arrived))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 20.0, nodes: int = SIDE * SIDE) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate, nodes)
    for coro in (s.setup(), s.traffic(), s.chaos(), s.checker()):
        sim.spawn(coro)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.net.bugs:
                raise s.net.bugs[0]
            sent = {v: t for v, t in s.sent.items() if a <= t < b}
            for v in sent:
                del s.sent[v]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "groups": {i.t0: [sorted(s.index[n] for n in g) for g in groups_for(i, s.ids, seed)]
                           for i in s.planned if a <= i.t0 < b},
                "tables": {
                    # (start, kind, node, value, end, ok)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped)
                    "msgs": s.messages(a, b),
                    # (sent, value): numbers broadcast this minute
                    "values": sorted((t, v) for v, t in sent.items()),
                    # (when, value, everywhere): a number reached every node, or was given up on
                    "done": sorted([(t, v, True) for t, v in _take(s.reached, 0, 0.0, b + DRAIN)]
                                   + [(t, v, False) for t, v in _take(s.lost, 0, 0.0, b + DRAIN)]),
                    # (time, missing values per node)
                    "lag": _take(s.lag, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
