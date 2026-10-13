"""Lab g_counter (Fly.io Gossip Glomers #4): one endless run on virtual time.

3 nodes on a simulated network (20 ms per message, a LAN) and Maelstrom's `seq-kv` service.
Clients send ~`rate` operations/s to random nodes: `add` (a small delta) and `read` (the
counter's value). The nodes keep nothing that matters in memory: the count lives in seq-kv,
which is sequentially consistent, so a read may return a value up to `stale` seconds old.

Incidents come at random, like in production: bursts of adds (a flash sale, a retry storm
from a client) and a slow network (a congested link). The first one is always a burst of
3x the adds at 0:20-0:30.

For every read the scenario records the band the value must fall in: at least every add
acknowledged `LAG` seconds before the read started, at most every add sent before it ended.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_right
from collections.abc import Iterator
from itertools import accumulate

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, KVService, Message, Network
from core.vtime import VirtualRun, now

LAB = "g_counter"
NAMES = ("CounterNode",)
PIECE = 60.0
DRAIN = 20.0
NODES = 3
STALE = 0.5  # seq-kv reads may be this many seconds old
LAG = STALE + 1.0  # a read must show every add acknowledged this long before it (1.5 s)
CLIENT_TIMEOUT = 1.0
ADD_SHARE = 0.6  # of client operations
LATENCY = 0.02  # a LAN: 20 ms per message
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "burst", 3.0, "flash_sale")
KINDS = [
    Kind("burst", 0.6, median=10.0, shortest=5.0, longest=20.0, severity=(2.5, 3.5), causes=(
        "flash_sale", "retry_loop", "batch_import")),
    Kind("slow", 0.4, median=10.0, shortest=5.0, longest=20.0, severity=(2.5, 4.0), causes=(
        "congested_link", "noisy_neighbour", "bad_mtu")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm before the next one: 15 s measured before it, and time to judge the last

ADD, READ = 0, 1
# Kinds of message, for the picture: client request, node -> kv, kv ok, kv conflict, reply, node <-> node.
CLIENT_REQ, KV_REQ, KV_OK, KV_ERR, REPLY, PEER = range(6)
KV_INDEX = NODES  # seq-kv is drawn as one more node


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class CountingKV(KVService):
    """seq-kv that also records every compare-and-swap: (time, node, succeeded)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cas_log: list[tuple[float, str, bool]] = []

    async def on_cas(self, msg: Message) -> None:
        key = msg.body.get("key")
        ok = (key in self.data and self.data[key] == msg.body.get("from")) or (
            key not in self.data and bool(msg.body.get("create_if_not_exists")))
        self.cas_log.append((now(), msg.src, ok))
        await super().on_cas(msg)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = Network(latency=LATENCY, jitter=0.2, seed=seed)
        self.kv = CountingKV("seq-kv", stale=STALE, seed=seed * 3 + 1)
        self.net.join(self.kv)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)} | {"seq-kv": KV_INDEX}
        self.code = code
        self.nodes: list = []
        self.client = Client("c1")
        self.net.join(self.client)
        self.planned: list[Planned] = []
        self.burst = 1.0
        self.ops: list[tuple] = []  # finished: (start, kind, node, delta or value, end, ok, low, high)
        self.reads: list[tuple] = []  # finished reads waiting for their band: (start, node, value, end, ok)
        self.invoked: list[tuple[float, int]] = []  # (time, delta) of recent adds sent
        self.acked: list[tuple[float, int]] = []  # (time, delta) of recent adds acknowledged
        self.inv_base = self.ack_base = 0  # totals of older adds, already forgotten
        self.open: dict[int, float] = {}
        self._seq = itertools.count()

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.CounterNode(n, self.ids)
            self.net.join(node)
            self.nodes.append(node)

    async def _op(self, kind: int, node: str, body: dict, delta: int = 0) -> None:
        k = next(self._seq)
        start = now()
        self.open[k] = start
        value, ok = delta, False
        try:
            reply = await self.client.rpc(node, body, timeout=CLIENT_TIMEOUT)
            ok = True
            if kind == READ:
                value = reply.get("value")
                ok = isinstance(value, int)
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the client gives up
            pass
        finally:
            self.open.pop(k, None)
        end = now()
        if kind == ADD:
            if ok:
                self.acked.append((end, delta))
            self.ops.append((start, ADD, self.index[node], delta, end, ok, 0, 0))
        else:
            self.reads.append((start, self.index[node], value if ok else -1, end, ok))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7 + 1)
        t = 0.5
        while True:
            t += rng.expovariate(self.rate * self.burst)
            await asyncio.sleep(max(0.0, t - now()))
            t = max(t, now())
            node = rng.choice(self.ids)
            if rng.random() < ADD_SHARE:
                delta = rng.randint(1, 5)
                self.invoked.append((now(), delta))
                asyncio.ensure_future(self._op(ADD, node, {"type": "add", "delta": delta}, delta))
            else:
                asyncio.ensure_future(self._op(READ, node, {"type": "read"}))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "burst":
                self.burst = inc.severity
            else:
                self.net.latency = LATENCY * inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.burst, self.net.latency = 1.0, LATENCY

    def banded(self, b: float) -> list[tuple]:
        """Reads that started before b, with the band their value must fall in."""
        inv_t = [t for t, _ in self.invoked]
        inv_sum = list(accumulate(d for _, d in self.invoked))
        acked = sorted(self.acked)
        ack_t = [t for t, _ in acked]
        ack_sum = list(accumulate(d for _, d in acked))

        def total(times: list[float], sums: list[int], t: float) -> int:
            i = bisect_right(times, t)
            return sums[i - 1] if i else 0

        inv_sum = [x + self.inv_base for x in inv_sum]
        ack_sum = [x + self.ack_base for x in ack_sum]

        out, keep = [], []
        for r in self.reads:
            (out if r[0] < b else keep).append(r)
        self.reads = keep
        rows = []
        for start, node, value, end, ok in out:
            low = max(self.ack_base, total(ack_t, ack_sum, start - LAG))
            high = max(self.inv_base, total(inv_t, inv_sum, end))
            rows.append((start, READ, node, value, end, ok, low, high))
        return rows

    def forget(self, cut: float) -> None:
        self.inv_base += sum(d for t, d in self.invoked if t < cut)
        self.invoked = [x for x in self.invoked if x[0] >= cut]
        self.acked.sort()
        self.ack_base += sum(d for t, d in self.acked if t < cut)
        self.acked = [x for x in self.acked if x[0] >= cut]

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages sent in [a, b): (sent, src, dest, arrived or None, kind). Clients are -1."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.sent < a:
                continue
            src, dst = self.index.get(d.src, -1), self.index.get(d.dest, -1)
            if src == -1:
                kind = CLIENT_REQ
            elif dst == KV_INDEX:
                kind = KV_REQ
            elif src == KV_INDEX:
                kind = KV_ERR if d.type == "error" else KV_OK
            elif dst == -1:
                kind = REPLY
            else:
                kind = PEER
            out.append((d.sent, src, dst, d.arrived, kind))
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
    for coro in (s.setup(), s.traffic(), s.chaos()):
        sim.spawn(coro)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.net.bugs:
                raise s.net.bugs[0]
            if any(t < b + DRAIN - 30.0 for t in s.open.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=30.0))
            s.ops.extend(s.banded(b))
            cas = [(t, s.index[n], ok) for t, n, ok in s.kv.cas_log if t < b]
            s.kv.cas_log[:] = [c for c in s.kv.cas_log if c[0] >= b]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    # (start, kind, node, delta or value read, end, ok, low, high)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None, kind); -1 = clients, 3 = seq-kv
                    "msgs": s.messages(a, b),
                    # (time, node, succeeded): every compare-and-swap seq-kv saw
                    "cas": sorted(c for c in cas if c[0] >= a),
                },
            }
            s.forget(b - LAG - 5.0)  # no later read can need adds older than this
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
