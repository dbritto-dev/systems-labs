"""Lab txn (Fly.io Gossip Glomers #6): one endless run on virtual time.

3 nodes on a simulated network (100 ms per message) hold a key/value store. Clients send
~`rate` transactions/s to random nodes: `txn` with 1-4 micro-operations, each a read
["r", key, null] or a write ["w", key, value]. Every write value is unique. A quarter of
the transactions write the same key twice (the first value is "intermediate": nobody else
should ever see it). Two hot keys get half of the operations; the other 98 keys are cold.

Incidents are network partitions, like in production: one node is cut off from the
others (clients still reach every node, so every transaction must still be answered).
The first one always cuts a node off at 0:20-0:30.

The checker looks at each node's `store` dict every 50 ms, outside the network (not
counted as traffic), to see how far behind each node is; and it checks every answer the
clients get for intermediate reads (G1b).
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

LAB = "txn"
NAMES = ("TxnNode",)
PIECE = 60.0
DRAIN = 20.0
KEYS = 100  # keys 0 and 1 are hot
HOT = 2
PROBE = 0.05  # how often the checker looks at every node's store
STALE_EVERY = 0.1  # how often each node's staleness is recorded
STALE_AFTER = 1.0  # a key is stale on a node if it is this far behind the newest value anywhere
CLIENT_TIMEOUT = 1.0
FORGET = 300.0  # forget values written this long ago (an old value left in a store counts as very old)
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "isolate", 1.0, "tor_switch")
KINDS = [
    Kind("isolate", 1.0, median=10.0, shortest=5.0, longest=25.0, causes=(
        "tor_switch", "firewall_port", "nic_drops", "zone_link")),
]
MEAN_GAP = 30.0
QUIET = 27.0  # calm before the next one: 15 s measured before it, 10 s to judge the last

# Columns of the tables.
TXN_START, TXN_NODE, TXN_END, TXN_OK, TXN_READS, TXN_WRITES, TXN_BAD = range(7)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def cut_off(inc: Planned, nodes: int, seed: int) -> int:
    """Which node the incident cuts off."""
    return random.Random(hash((seed, inc.t0)) & 0xFFFFFFFF).randrange(nodes)


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
        self.planned: list[Planned] = []
        self.txns: list[tuple] = []  # finished: (start, node, end, ok, reads, writes, intermediate reads)
        self.anomalies: list[tuple] = []  # (when, node, key, value): a G1b intermediate read
        self.stale: list[tuple] = []  # (time, stale keys per node)
        self.issued: dict[int, float] = {}  # value -> when its transaction was sent
        self.intermediate: dict[int, int] = {}  # value -> the transaction that overwrote it itself
        self._txn_ids = itertools.count(1)
        self._next_value = itertools.count(1)
        self.open: dict[int, float] = {}

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.TxnNode(n, self.ids)
            if not isinstance(getattr(node, "store", None), dict):
                raise AttributeError(lab_text(LAB).STRINGS["no_store"])
            self.net.join(node)
            self.nodes.append(node)

    def make_txn(self, rng: random.Random) -> tuple[int, list[list]]:
        """A transaction: 1-4 reads and writes; a quarter of them write one key twice."""
        tid = next(self._txn_ids)
        ops: list[list] = []

        def key() -> int:
            return rng.randrange(HOT) if rng.random() < 0.5 else rng.randrange(HOT, KEYS)

        for _ in range(rng.randint(1, 3)):
            if rng.random() < 0.5:
                ops.append(["r", key(), None])
            else:
                ops.append(["w", key(), self.value(tid)])
        if rng.random() < 0.25:  # write one key twice: the first value is intermediate
            k = key()
            first = self.value(tid)
            ops.insert(0, ["w", k, first])
            ops.append(["w", k, self.value(tid)])
            self.intermediate[first] = tid
        return tid, ops

    def value(self, tid: int) -> int:
        v = next(self._next_value)
        self.issued[v] = now()
        return v

    async def one(self, node: str, tid: int, ops: list[list]) -> None:
        start = now()
        self.open[tid] = start
        ok, reads, bad = False, 0, 0
        try:
            reply = await self.client.rpc(node, {"type": "txn", "txn": ops}, timeout=CLIENT_TIMEOUT)
            ok = True
            for op in reply.get("txn", []):
                if op[0] == "r":
                    reads += 1
                    writer = self.intermediate.get(op[2]) if op[2] is not None else None
                    if writer is not None and writer != tid:
                        bad += 1
                        self.anomalies.append((now(), self.index[node], op[1], op[2]))
        except Exception:  # noqa: BLE001 - no answer in time: not available
            pass
        finally:
            self.open.pop(tid, None)
        writes = sum(1 for op in ops if op[0] == "w")
        self.txns.append((start, self.index[node], now(), ok, reads, writes, bad))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 5)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            tid, ops = self.make_txn(rng)
            asyncio.ensure_future(self.one(rng.choice(self.ids), tid, ops))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            alone = self.ids[cut_off(inc, len(self.ids), self.seed)]
            self.net.partition([{alone}, set(self.ids) - {alone}])
            await asyncio.sleep(inc.t1 - now())
            self.net.heal()

    async def checker(self) -> None:
        """How far behind is each node? A key is stale on a node when another node has had a
        newer value of it for more than 1 s (values written in the same 200 ms count as the
        same age: when two writes cross, the newest stamp may win, not the newest issue)."""
        next_stale = 0.0
        next_forget = FORGET
        while True:
            await asyncio.sleep(PROBE)
            t = now()
            if t >= next_stale:
                next_stale = t + STALE_EVERY
                issued = self.issued
                stores = [node.store for node in self.nodes]
                stale = [0] * len(stores)
                for k in range(KEYS):
                    ages = [issued.get(s.get(k), -1e9) if k in s else None for s in stores]
                    settled = [a for a in ages if a is not None and a <= t - STALE_AFTER]
                    if not settled:
                        continue
                    newest = max(settled)  # the newest value any node has had for over a second
                    for i, a in enumerate(ages):
                        if a is None or a < newest - 0.2:
                            stale[i] += 1
                self.stale.append((t, tuple(stale)))
            if t >= next_forget:
                next_forget = t + 60.0
                old = [v for v, when in self.issued.items() if t - when > FORGET]
                for v in old:
                    del self.issued[v]
                    self.intermediate.pop(v, None)

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


def stream(variant="main", seed: int = 1, rate: float = 40.0, nodes: int = 3) -> Iterator[dict]:
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
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "cut": {i.t0: cut_off(i, nodes, seed) for i in s.planned if a <= i.t0 < b},
                "tables": {
                    # (start, node, end, ok, reads, writes, intermediate reads)
                    "txns": _take(s.txns, TXN_START, a, b),
                    # (sent, src, dest, arrived or None if dropped)
                    "msgs": s.messages(a, b),
                    # (when, node, key, value): a read that saw another transaction's intermediate write
                    "anomalies": _take(s.anomalies, 0, a, b),
                    # (time, stale keys per node)
                    "stale": _take(s.stale, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
