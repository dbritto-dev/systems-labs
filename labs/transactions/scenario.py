"""Lab transactions (Fly.io Gossip Glomers #6): one endless run on virtual time.

3 nodes on a simulated network (100 ms per message) hold a key/value store. Clients send
~`rate` transactions/s to random nodes: `txn` with 1-4 micro-operations, each a read
["r", key, null] or a write ["w", key, value]. Every write value is unique. A quarter of
the transactions write the same key twice (the first value is "intermediate": nobody else
should ever see it). Two hot keys get half of the operations; the other 98 keys are cold.

Incidents are network partitions, like in production: one node is cut off from the
others (clients still reach every node, so every transaction must still be answered).
The first one always cuts a node off at 0:20-0:30.

The checker looks at each node's `store` dict every 50 ms, outside the network (not
counted as traffic), to see how far behind each node is. It also notes every write to a
store as it happens (the store is wrapped), to catch dirty writes (G0): two transactions that
wrote the same keys, applied T then U on one key and U then T on another. It checks every answer the clients
get for the anomalies read committed forbids, as in Fly.io 6c: aborted reads (G1a: a value
written by a transaction the node aborted with error 30), intermediate reads (G1b) and
circular information flow (G1c, between two transactions: each read the other's write).
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Network, RPCError
from core.vtime import VirtualRun, now

LAB = "transactions"
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

TXN_ABORTED = 30  # Maelstrom's txn-conflict error: the transaction was aborted

# Columns of the tables.
TXN_START, TXN_NODE, TXN_END, TXN_OK, TXN_READS, TXN_WRITES, TXN_BAD = range(7)
# Kinds of anomaly.
G1A, G1B, G1C = range(3)


class Watched(dict):
    """A node's store that tells the checker every write to it (old value, new value), in order."""

    def __init__(self, data: dict, noted) -> None:
        super().__init__(data)
        self._noted = noted

    def __setitem__(self, key, value) -> None:
        old = self.get(key)
        super().__setitem__(key, value)
        if old != value:
            self._noted(key, old, value)

    def update(self, *args, **kwargs) -> None:
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


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
        self.anomalies: list[tuple] = []  # (when, node, key, value, kind): a G1a, G1b or G1c read
        self.g0: list[tuple] = []  # (when, node, key): a node holds a mix of two transactions' writes
        self.writer: dict[int, int] = {}  # value -> the transaction that wrote it
        self.final: dict[int, dict[int, int]] = {}  # tid -> {key: its last value}, for multi-key writers
        self.reads_from: dict[int, set[int]] = {}  # tid -> the transactions whose writes it read
        self.aborted: set[int] = set()  # values written by aborted transactions
        self._order: dict[tuple, set[int]] = {}  # (node, T, U) -> keys where the node applied T's write, then U's
        self._g0_seen: set[tuple] = set()
        self._next_trim = 0.0
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
        self.watch()

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
        last = {key: v for op, key, v in ops if op == "w"}
        if len(last) >= 2:
            self.final[tid] = last
        return tid, ops

    def value(self, tid: int) -> int:
        v = next(self._next_value)
        self.issued[v] = now()
        self.writer[v] = tid
        return v

    async def one(self, node: str, tid: int, ops: list[list]) -> None:
        start = now()
        self.open[tid] = start
        ok, reads, bad = False, 0, 0
        try:
            reply = await self.client.rpc(node, {"type": "txn", "txn": ops}, timeout=CLIENT_TIMEOUT)
            ok = self.well_formed(ops, reply)
            seen: set[int] = set()
            for op in reply.get("txn", []):
                if op[0] != "r" or op[2] is None:
                    reads += op[0] == "r"
                    continue
                reads += 1
                kind = None
                if op[2] in self.aborted:
                    kind = G1A  # it read a write that was aborted
                elif (w := self.intermediate.get(op[2])) is not None and w != tid:
                    kind = G1B  # it read another transaction's intermediate write
                elif (w := self.writer.get(op[2])) is not None and w != tid:
                    seen.add(w)
                    if tid in self.reads_from.get(w, ()):
                        kind = G1C  # it read w's write, and w read one of its own: a cycle
                if kind is not None:
                    bad += 1
                    self.anomalies.append((now(), self.index[node], op[1], op[2], kind))
            self.reads_from[tid] = seen
        except RPCError as e:
            if e.code == TXN_ABORTED:  # aborted: an answer (allowed), and its writes must never be read
                ok = True
                self.aborted.update(v for op, _, v in ops if op == "w")
        except Exception:  # noqa: BLE001 - no answer in time: not available
            pass
        finally:
            self.open.pop(tid, None)
        writes = sum(1 for op in ops if op[0] == "w")
        self.txns.append((start, self.index[node], now(), ok, reads, writes, bad))

    @staticmethod
    def well_formed(ops: list[list], reply: dict) -> bool:
        """A txn_ok with the same micro-operations, in order: writes echoed, each read filled in."""
        got = reply.get("txn")
        if reply.get("type") != "txn_ok" or not isinstance(got, list) or len(got) != len(ops):
            return False
        for (op, key, value), r in zip(ops, got):
            if not isinstance(r, (list, tuple)) or len(r) != 3 or r[0] != op or r[1] != key:
                return False
            if op == "w" and r[2] != value:
                return False
        return True

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
            self.watch()
            if t >= self._next_trim:
                self._next_trim = t + 10.0
                self.trim(t)
            if t >= next_forget:
                next_forget = t + 60.0
                old = [v for v, when in self.issued.items() if t - when > FORGET]
                for v in old:
                    del self.issued[v]
                    self.intermediate.pop(v, None)
                    self.writer.pop(v, None)
                    self.aborted.discard(v)
                done = {self.writer[v] for v in self.issued if v in self.writer}
                for tid in [tid for tid in self.reads_from if tid not in done]:
                    del self.reads_from[tid]

    def watch(self) -> None:
        """Wrap each node's store so every write to it is noted, in order (again if the code replaced it)."""
        for i, node in enumerate(self.nodes):
            if not isinstance(node.store, Watched):
                node.store = Watched(node.store, lambda k, old, new, i=i: self.applied(i, k, old, new))

    def applied(self, i: int, k, old, new) -> None:
        """G0: node i replaced old with new at key k. If it applied T's write before U's on one key and U's
        before T's on another (both wrote both), their writes are interleaved: a dirty write."""
        t_old, t_new = self.writer.get(old), self.writer.get(new)
        if t_old is None or t_new is None or t_old == t_new or t_old not in self.final or t_new not in self.final:
            return  # only transactions that wrote several keys can interleave
        self._order.setdefault((i, t_old, t_new), set()).add(k)
        other = self._order.get((i, t_new, t_old))
        pair = (i, min(t_old, t_new), max(t_old, t_new))
        if other and other - {k} and pair not in self._g0_seen:
            self._g0_seen.add(pair)
            self.g0.append((now(), i, k))

    def trim(self, t: float) -> None:
        """Forget the write order of transactions long done."""
        live = {tid for tid, last in self.final.items()
                if t - self.issued.get(next(iter(last.values())), -1e9) < 30.0}
        self.final = {tid: w for tid, w in self.final.items() if tid in live}
        self._order = {key: ks for key, ks in self._order.items() if key[1] in live and key[2] in live}
        self._g0_seen = {key for key in self._g0_seen if key[1] in live and key[2] in live}

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
                    # (when, node, key, value, kind): a read that saw an aborted (G1a) or intermediate
                    # (G1b) write, or closed a cycle (G1c)
                    "anomalies": _take(s.anomalies, 0, a, b),
                    # (when, node, key): a node holds a mix of two transactions' writes (G0)
                    "g0": _take(s.g0, 0, a, b),
                    # (time, stale keys per node)
                    "stale": _take(s.stale, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
