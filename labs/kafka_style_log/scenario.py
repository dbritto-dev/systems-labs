"""Lab kafka_style_log (Fly.io Gossip Glomers #5): one endless run on virtual time.

Two nodes and Maelstrom's `lin-kv` service on a fast network (~10 ms per message).
Clients send ~`rate` operations/s to either node: `send` (append a message to a key's log),
`poll` (messages from an offset on), `commit_offsets` and `list_committed_offsets`.

Incidents, like in production: a burst on one hot key (a producer replays a backlog), or the
`lin-kv` store slows down (compaction, a noisy neighbour). The first one is always a burst
at 0:20-0:30.

The checker watches every reply, as Maelstrom's kafka checker does:
- duplicate: two acknowledged sends got the same offset for the same key;
- lost write: a poll returned offset o2 but skipped an earlier offset that was already
  acknowledged (or returned a different message at an offset);
- lost commit: list_committed_offsets returned less than an acknowledged commit.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_left, insort
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, KVService, Message, Network
from core.vtime import VirtualRun, now

LAB = "kafka_style_log"
NAMES = ("KafkaNode",)
PIECE = 60.0
DRAIN = 5.0
NODES = 2
KEYS = 10
LATENCY = 0.01  # seconds per message (a fast LAN)
CLIENT_TIMEOUT = 1.0
CONSUMERS = 4
HOT_SHARE = 0.4  # during a burst, this share of operations are sends to the hot key
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "burst", 2.5, "replay")
KINDS = [
    Kind("burst", 0.6, median=10.0, shortest=6.0, longest=20.0, severity=(2.0, 2.5), causes=(
        "replay", "flash_sale", "retry_storm")),
    Kind("slowkv", 0.4, median=10.0, shortest=6.0, longest=18.0, severity=(2.0, 4.0), causes=(
        "compaction", "noisy_disk", "lost_replica")),
]
MEAN_GAP = 25.0
QUIET = 27.0  # 15 s measured before the next one, and 10 s after the last

# Operation kinds.
SEND, POLL, COMMIT, LIST = range(4)
# Anomaly kinds.
DUPLICATE, LOST_WRITE, LOST_COMMIT = range(3)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def key_name(k: int) -> str:
    return f"k{k}"


class SlowKV(KVService):
    """lin-kv, with an extra delay while it is slow."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.delay = 0.0

    async def _slow(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)

    async def on_read(self, msg: Message) -> None:
        await self._slow()
        await super().on_read(msg)

    async def on_write(self, msg: Message) -> None:
        await self._slow()
        await super().on_write(msg)

    async def on_cas(self, msg: Message) -> None:
        await self._slow()
        await super().on_cas(msg)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.net = Network(latency=LATENCY, jitter=0.3, seed=seed)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.index["lin-kv"] = NODES
        self.kv = SlowKV("lin-kv")
        self.net.join(self.kv)
        self.client = Client("c1")
        self.net.join(self.client)
        self.nodes: list = []
        self.planned: list[Planned] = []
        self.burst: tuple[int, float] | None = None  # (hot key, rate multiplier)
        self.hot: dict[float, int] = {}  # incident start -> its hot key
        # What the checker knows.
        self.acked: list[dict[int, tuple[int, float]]] = [{} for _ in range(KEYS)]  # offset -> (msg, acked at)
        self.offsets: list[list[int]] = [[] for _ in range(KEYS)]  # sorted acked offsets
        self.committed: list[list[tuple[float, int]]] = [[] for _ in range(KEYS)]  # (acked at, offset)
        self.positions = [[0] * KEYS for _ in range(CONSUMERS)]  # where each consumer polls from
        self.ops: list[tuple] = []  # (start, kind, node, key, end, ok, bad)
        self.anomalies: list[tuple] = []  # (time, kind, node, key)
        self.open: dict[int, float] = {}
        self._seq = itertools.count()
        self._msg = itertools.count(1)

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.KafkaNode(n, self.ids)
            self.net.join(node)
            self.nodes.append(node)

    # ---- the workload

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        t = 0.2
        while True:
            boost = self.burst[1] if self.burst else 1.0
            t += rng.expovariate(self.rate * boost)
            await asyncio.sleep(max(0.0, t - now()))
            node = rng.choice(self.ids)
            consumer = rng.randrange(CONSUMERS)
            r = rng.random()
            if self.burst and r < HOT_SHARE:
                key = self.burst[0]
                asyncio.ensure_future(self.send(node, key))
                continue
            key = rng.randrange(KEYS)
            if r < 0.5:
                asyncio.ensure_future(self.send(node, key))
            elif r < 0.8:
                keys = rng.sample(range(KEYS), 2)
                asyncio.ensure_future(self.poll(node, consumer, keys))
            elif r < 0.9:
                asyncio.ensure_future(self.commit(node, consumer))
            else:
                asyncio.ensure_future(self.list(node, rng.sample(range(KEYS), 3)))

    async def _rpc(self, node: str, body: dict) -> tuple[float, dict | None]:
        k = next(self._seq)
        start = now()
        self.open[k] = start
        try:
            reply = await self.client.rpc(node, body, timeout=CLIENT_TIMEOUT)
        except Exception:  # noqa: BLE001 - a timeout or an error reply
            reply = None
        finally:
            self.open.pop(k, None)
        return start, reply

    def _bad(self, kind: int, node: str, key: int) -> None:
        self.anomalies.append((now(), kind, self.index[node], key))

    async def send(self, node: str, key: int) -> None:
        msg = next(self._msg)
        start, reply = await self._rpc(node, {"type": "send", "key": key_name(key), "msg": msg})
        bad = 0
        if reply is not None:
            offset = reply.get("offset")
            known = self.acked[key].get(offset)
            if known is not None and known[0] != msg:
                self._bad(DUPLICATE, node, key)
                bad = 1
            elif known is None and isinstance(offset, int):
                self.acked[key][offset] = (msg, now())
                insort(self.offsets[key], offset)
        self.ops.append((start, SEND, self.index[node], key, now(), reply is not None, bad))

    async def poll(self, node: str, consumer: int, keys: list[int]) -> None:
        pos = self.positions[consumer]
        asked = {key_name(k): pos[k] for k in keys}
        start, reply = await self._rpc(node, {"type": "poll", "offsets": asked})
        bad = 0
        if reply is not None:
            got = reply.get("msgs", {})
            for k in keys:
                pairs = sorted((p[0], p[1]) for p in got.get(key_name(k), []) if p[0] >= pos[k])
                if not pairs:
                    continue
                seen = dict(pairs)
                top = pairs[-1][0]
                acked, offs = self.acked[k], self.offsets[k]
                lost = any(acked[o][1] < start and o not in seen
                           for o in offs[bisect_left(offs, pos[k]):bisect_left(offs, top)])
                wrong = any(o in acked and acked[o][0] != m for o, m in pairs)
                if lost or wrong:
                    self._bad(LOST_WRITE, node, k)
                    bad += 1
                pos[k] = max(pos[k], top + 1)
        self.ops.append((start, POLL, self.index[node], keys[0], now(), reply is not None, bad))

    async def commit(self, node: str, consumer: int) -> None:
        pos = self.positions[consumer]
        offsets = {key_name(k): pos[k] - 1 for k in range(KEYS) if pos[k] > 0}
        if not offsets:
            return
        start, reply = await self._rpc(node, {"type": "commit_offsets", "offsets": offsets})
        if reply is not None:
            for name, off in offsets.items():
                k = int(name[1:])
                self.committed[k].append((now(), off))
                if len(self.committed[k]) > 64:
                    del self.committed[k][:-64]
        self.ops.append((start, COMMIT, self.index[node], -1, now(), reply is not None, 0))

    async def list(self, node: str, keys: list[int]) -> None:
        start, reply = await self._rpc(node, {"type": "list_committed_offsets",
                                              "keys": [key_name(k) for k in keys]})
        bad = 0
        if reply is not None:
            got = reply.get("offsets", {})
            for k in keys:
                must = max((o for t, o in self.committed[k] if t < start), default=None)
                if must is not None and got.get(key_name(k), -1) < must:
                    self._bad(LOST_COMMIT, node, k)
                    bad += 1
        self.ops.append((start, LIST, self.index[node], keys[0], now(), reply is not None, bad))

    async def chaos(self) -> None:
        rng = random.Random(self.seed * 5 + 9)
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "burst":
                self.burst = (rng.randrange(KEYS), inc.severity)
                self.hot[inc.t0] = self.burst[0]
            else:
                self.kv.delay = LATENCY * inc.severity * 2
            await asyncio.sleep(inc.t1 - now())
            self.burst = None
            self.kv.delay = 0.0

    def prune(self) -> None:
        """Forget acknowledged offsets every consumer has polled past (an endless run stays small)."""
        for k in range(KEYS):
            low = min(p[k] for p in self.positions)
            offs = self.offsets[k]
            i = bisect_left(offs, low)
            for o in offs[:i]:
                self.acked[k].pop(o, None)
            del offs[:i]

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between nodes and lin-kv sent in [a, b): (sent, src, dest, arrived or None)."""
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


def stream(variant="main", seed: int = 1, rate: float = 30.0) -> Iterator[dict]:
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
            s.prune()
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "hot": {t: k for t, k in s.hot.items() if a <= t < b},
                "tables": {
                    # (start, kind, node, key, end, ok, anomalies)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None): between nodes and lin-kv (index 2)
                    "msgs": s.messages(a, b),
                    # (time, kind, node, key)
                    "anomalies": _take(s.anomalies, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
