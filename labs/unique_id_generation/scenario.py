"""Lab unique_id_generation (Fly.io Gossip Glomers #1 and #2): one endless run on virtual time.

5 nodes on a simulated network (100 ms per message). Clients send ~`rate` requests/s to
random nodes: some `echo` (send it back), most `generate` (give me an ID nobody else has).

Incidents come at random, like in production:
- split: the network between the nodes partitions (clients still reach every node);
- clock: NTP steps one node's wall clock back by 1.5-3 s;
- migrate: a VM live migration does both: one node is cut off and its clock steps back.
The first one is always a migration at 0:20-0:30.

Each node reads its wall clock with `self.wall_ms()` (milliseconds since 1970). The
scenario sets it, so it can jump backwards like a real clock.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Network
from core.vtime import VirtualRun, now

LAB = "unique_id_generation"
NAMES = ("UniqueIdNode",)
PIECE = 60.0
DRAIN = 10.0
NODES = 5
CLIENT_TIMEOUT = 1.0
ECHO_SHARE = 0.2
EPOCH_MS = 1_767_225_600_000  # 2026-01-01 00:00 UTC: the wall clock reads this at 0:00
# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 30.0, "migrate", 2.0, "live_migration")
KINDS = [
    Kind("split", 0.4, median=9.0, shortest=5.0, longest=20.0, causes=(
        "switch_failed", "zone_link", "firewall")),
    Kind("clock", 0.35, median=8.0, shortest=5.0, longest=15.0, severity=(1.5, 3.0), causes=(
        "ntp_step", "leap_smear", "hypervisor_resync")),
    Kind("migrate", 0.25, median=10.0, shortest=6.0, longest=18.0, severity=(1.5, 3.0), causes=(
        "live_migration", "host_drained")),
]
MEAN_GAP = 30.0
QUIET = 22.0

ECHO, GENERATE = 0, 1


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, seed: int) -> int:
    """The node the incident hits (cut off, and/or its clock stepped back)."""
    return random.Random(f"{seed}:{inc.t0}:victim").randrange(NODES)  # a str seed is stable across runs


def groups_for(inc: Planned, seed: int) -> list[list[int]] | None:
    """Who can still talk to whom during the incident (None: the network is fine)."""
    if inc.kind == "clock":
        return None
    v = victim(inc, seed)
    if inc.kind == "migrate":
        return [[v], [i for i in range(NODES) if i != v]]
    rng = random.Random(f"{seed}:{inc.t0}:split")
    small = sorted(rng.sample(range(NODES), 2))
    return [small, [i for i in range(NODES) if i not in small]]


def compact(ident) -> bool:
    """A 64-bit database key: an int from 0 to 2**63 - 1."""
    return isinstance(ident, int) and not isinstance(ident, bool) and 0 <= ident < 2 ** 63


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate, self.code = seed, rate, code
        self.net = Network(latency=0.1, jitter=0.2, seed=seed)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.nodes: list = []
        self.client = Client("c1")
        self.net.join(self.client)
        self.offset = [0.0] * NODES  # each node's wall clock minus true time (seconds)
        self.planned: list[Planned] = []
        self.ops: list[tuple] = []  # finished requests
        self.seen: set = set()  # every id ever handed out
        self.open_ops: dict[int, float] = {}
        self._seq = itertools.count()

    async def setup(self) -> None:
        for i, n in enumerate(self.ids):
            node = self.code.UniqueIdNode(n, self.ids)
            node.wall_ms = (lambda i=i: EPOCH_MS + int((now() + self.offset[i]) * 1000))
            self.net.join(node)
            self.nodes.append(node)

    async def _op(self, kind: int, node: str, body: dict) -> None:
        k = next(self._seq)
        start = now()
        self.open_ops[k] = start
        ident, ok, dup, small = None, False, False, False
        try:
            reply = await self.client.rpc(node, body, timeout=CLIENT_TIMEOUT)
            if kind == ECHO:
                ok = reply.get("type") == "echo_ok" and reply.get("echo") == body["echo"]
            else:
                ident = reply.get("id")
                ok = reply.get("type") == "generate_ok" and ident is not None
                if ok:
                    key = (type(ident).__name__, ident) if isinstance(ident, (int, str)) else repr(ident)
                    dup = key in self.seen
                    self.seen.add(key)
                    small = compact(ident)
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the request failed
            ok = False
        finally:
            self.open_ops.pop(k, None)
        self.ops.append((start, kind, self.index[node], now(), ok, ident if small else None, dup, small))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        for t in arrivals(self.rate, self.seed, 0.2, rng):
            await asyncio.sleep(t - now())
            node = rng.choice(self.ids)
            if rng.random() < ECHO_SHARE:
                asyncio.ensure_future(self._op(ECHO, node, {"type": "echo", "echo": f"hello {rng.randrange(10**6)}"}))
            else:
                asyncio.ensure_future(self._op(GENERATE, node, {"type": "generate"}))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            groups = groups_for(inc, self.seed)
            v = victim(inc, self.seed)
            if groups is not None:
                self.net.partition([{self.ids[i] for i in g} for g in groups])
            if inc.kind in ("clock", "migrate"):
                self.offset[v] -= inc.severity  # NTP steps the clock back
            await asyncio.sleep(inc.t1 - now())
            self.net.heal()
            if inc.kind in ("clock", "migrate"):
                self.offset[v] = 0.0  # corrected again (forward jumps are harmless)

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
            mine = [i for i in s.planned if a <= i.t0 < b]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in mine],
                "groups": {i.t0: groups_for(i, seed) for i in mine},
                "victims": {i.t0: victim(i, seed) for i in mine},
                "tables": {
                    # (start, kind, node, end, ok, id if it is a 64-bit int else None, duplicate, compact)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped)
                    "msgs": s.messages(a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
