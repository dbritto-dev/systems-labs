"""Lab merkle_anti_entropy: replicas that drift apart, one endless run on virtual time.

4 replicas (n0..n3) on a simulated network (~100 ms per message), each with a full copy of the
same 20,000 keys. Clients write ~100 keys a second, each to one replica (the coordinator), which
replicates it to the others in batches every 0.1 s (see api.py); they read ~200 keys a second from
any replica that is up, half of them keys written recently.

Normal replication sometimes misses writes, and nothing tells you. Incidents, like in production:
a replica is down long enough for the hints kept for it to overflow (it comes back without the
writes past the hint window), a network blip drops replication batches to and from one replica,
a bad disk loses keys on one replica, or an operator restores an old backup over a key range of
one replica. The first incident is always n2 down at 0:20-0:30.

The checker knows the truth (the latest version of every key) and, every 250 ms, counts the keys
each replica holds an older version of (writes still replicating, under 0.5 s old, do not count);
every read is checked against the latest version.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Network
from core.vtime import VirtualRun, now
from labs.merkle_anti_entropy import lab
from labs.merkle_anti_entropy.api import KEYS, Replica, entries, key_of

LAB = "merkle_anti_entropy"
NAMES = ("ReplicaNode",)
PIECE = 60.0
DRAIN = 5.0
READS = 2.0  # reads per write
POOL = 3_000  # the most recently written keys ...
POOL_SHARE = 0.5  # ... are what half of the reads ask for (feeds, recent activity)
SAMPLE = 0.25  # the checker looks this often
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "down", 1.0, "kernel_panic")
KINDS = [
    Kind("down", 0.3, median=12.0, shortest=6.0, longest=30.0, causes=("kernel_panic", "oom_kill", "host_reboot")),
    Kind("blip", 0.3, median=4.0, shortest=2.5, longest=8.0, causes=("switch_failover", "nic_reset", "conntrack")),
    Kind("disk", 0.2, severity=(200.0, 800.0), causes=("bit_rot", "bad_sector", "raid_rebuild")),
    Kind("restore", 0.2, severity=(300.0, 1200.0), causes=("wrong_snapshot", "operator_error", "rollback")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # calm after an incident: 20 s to repair it, then a baseline before the next

READ, WRITE = 0, 1


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def target(inc: Planned, seed: int) -> int:
    """The replica an incident hits. The first one is always n2."""
    if inc.t0 == FIRST.t0:
        return 2
    return random.Random(f"{seed}:{inc.t0}:node").randrange(lab.REPLICAS)


def key_span(inc: Planned, seed: int) -> tuple[int, int]:
    """A restored backup: (first key index, how many keys), a contiguous range."""
    n = int(inc.severity)
    return random.Random(f"{seed}:{inc.t0}:span").randrange(KEYS - n), n


class _Net(Network):
    """The network, also metering what each message costs (its entries)."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.meter: list[tuple] = []  # (delivery, repair?, entries)

    def send(self, src: str, dest: str, body: dict) -> None:
        super().send(src, dest, body)
        self.meter.append((self.log[-1], body.get("type") != "replicate", entries(body)))


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.rng = random.Random(seed * 17 + 3)
        self.net = _Net(latency=0.1, jitter=0.2, seed=seed)
        self.ids = [f"n{i}" for i in range(lab.REPLICAS)]
        self.code = code
        self.nodes: list[Replica] = []
        self.index: dict[int, int] = {}  # id(node) -> its index
        self.cur: dict[str, tuple[int, int]] = {}  # key -> the latest (version, value)
        self.prev: dict[str, tuple[int, int]] = {}  # key -> the one before (what an old backup holds)
        self.at: dict[str, float] = {}  # key -> when its latest version was written
        self.behind: list[set[str]] = [set() for _ in self.ids]  # keys each replica holds older
        self.recent: deque[tuple[float, str]] = deque()  # (time, key) written in the last SETTLE s
        self.pool: deque[str] = deque(maxlen=POOL)
        self.down: set[int] = set()
        self.version = 2 * KEYS
        self.planned: list[Planned] = []
        self.facts: dict[float, dict] = {}  # incident start -> what it did
        self.ops: list[tuple] = []  # (start, READ or WRITE, node, end, stale)
        self.state: list[tuple] = []  # (time, divergent keys per replica, hash work, keys repaired)
        self._hashed = [0] * lab.REPLICAS
        self._fixed = [0] * lab.REPLICAS

    # ---- the truth

    def watch(self, node: Replica, key: str, version: int) -> None:
        r = self.index[id(node)]
        if version >= self.cur[key][0]:
            self.behind[r].discard(key)
        else:
            self.behind[r].add(key)

    async def setup(self) -> None:
        rng = random.Random(self.seed * 17 + 4)
        rows = {}
        for i in range(KEYS):
            key = key_of(i)
            self.prev[key] = (i + 1, rng.getrandbits(30))
            rows[key] = self.cur[key] = (KEYS + i + 1, rng.getrandbits(30))
            self.at[key] = -1e9
        for n in self.ids:
            node = self.code.ReplicaNode(n, self.ids)
            if not isinstance(node, Replica):
                raise TypeError(lab_text(LAB).STRINGS["not_replica"])
            self.index[id(node)] = len(self.nodes)
            self.net.join(node)
            self.nodes.append(node)
            node.load(rows)
            node.watch = self.watch

    # ---- clients

    def write(self, t: float) -> None:
        up = [i for i in range(lab.REPLICAS) if i not in self.down]
        c = self.rng.choice(up)
        key = key_of(self.rng.randrange(KEYS))
        self.version += 1
        entry = (self.version, self.rng.getrandbits(30))
        self.prev[key], self.cur[key], self.at[key] = self.cur[key], entry, t
        for r in range(lab.REPLICAS):
            if r != c:
                self.behind[r].add(key)
        self.nodes[c].write(key, *entry)
        self.recent.append((t, key))
        self.pool.append(key)
        self.ops.append((t, WRITE, c, t + self.rng.uniform(0.002, 0.006), False))

    def read(self, t: float) -> None:
        up = [i for i in range(lab.REPLICAS) if i not in self.down]
        r = self.rng.choice(up)
        if self.pool and self.rng.random() < POOL_SHARE:
            key = self.pool[self.rng.randrange(len(self.pool))]
        else:
            key = key_of(self.rng.randrange(KEYS))
        stale = self.nodes[r].version(key) < self.cur[key][0] and self.at[key] < t - lab.SETTLE
        self.ops.append((t, READ, r, t + self.rng.uniform(0.002, 0.006), stale))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 17 + 5)
        share = 1.0 / (1.0 + READS)
        for t in arrivals(self.rate * (1.0 + READS), self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            if rng.random() < share:
                self.write(t)
            else:
                self.read(t)

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            k = target(inc, self.seed)
            name = self.ids[k]
            fact: dict = {"node": k}
            self.facts[inc.t0] = fact
            others = [n for i, n in enumerate(self.nodes) if i != k]
            if inc.kind in ("down", "blip"):
                self.net.partition([{name}, {n for n in self.ids if n != name}])
                if inc.kind == "down":  # the others know: they keep hints for it
                    self.down.add(k)
                    for node in others:
                        node.down_peers.add(name)
                overflow = sum(node.overflow for node in others)
                await asyncio.sleep(inc.t1 - now())
                self.net.heal()
                if inc.kind == "down":
                    self.down.discard(k)
                    for node in others:
                        node.peer_up(name)
                    fact["n"] = sum(node.overflow for node in others) - overflow
            elif inc.kind == "disk":
                keys = [key_of(i) for i in random.Random(f"{self.seed}:{inc.t0}:keys").sample(range(KEYS),
                                                                                            int(inc.severity))]
                for key in keys:
                    self.nodes[k].force(key, None)
                fact["n"] = len(keys)
            else:  # restore: an old backup of a key range, over the replica's newer data
                lo, n = key_span(inc, self.seed)
                for i in range(lo, lo + n):
                    key = key_of(i)
                    self.nodes[k].force(key, self.prev[key])
                fact.update(lo=lo, n=n)

    async def checker(self) -> None:
        """Every 250 ms: keys each replica holds older than the latest, hash work, keys repaired."""
        while True:
            await asyncio.sleep(SAMPLE)
            t = now()
            while self.recent and self.recent[0][0] < t - lab.SETTLE:
                self.recent.popleft()
            fresh = {key for _, key in self.recent}
            diverged = tuple(len(b) - sum(1 for key in fresh if key in b) for b in self.behind)
            hashed = tuple(n.hashed - h for n, h in zip(self.nodes, self._hashed))
            fixed = tuple(n.fixed - f for n, f in zip(self.nodes, self._fixed))
            self._hashed = [n.hashed for n in self.nodes]
            self._fixed = [n.fixed for n in self.nodes]
            self.state.append((t, diverged, hashed, fixed))

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between replicas sent in [a, b): (sent, src, dest, arrived or None, repair?, entries)."""
        self.net.log.clear()  # the meter holds what we need
        out, keep = [], []
        for d, repair, n in self.net.meter:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append((d, repair, n))  # later, or still on the wire
            elif d.sent >= a:
                out.append((d.sent, int(d.src[1:]), int(d.dest[1:]), d.arrived, repair, n))
        self.net.meter[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 100.0) -> Iterator[dict]:
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
            new = [i for i in s.planned if a <= i.t0 < b]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in new],
                "facts": {t0: dict(f) for t0, f in s.facts.items() if t0 >= a - PIECE},
                "tables": {
                    # (start, READ or WRITE, replica, end, stale read?)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped, repair? (else replication), entries)
                    "msgs": s.messages(a, b),
                    # (time, divergent keys per replica, hash work per replica, keys repaired per replica)
                    "state": _take(s.state, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
