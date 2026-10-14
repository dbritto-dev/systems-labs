"""Lab consistent_hashing: one endless run on virtual time, handed out a minute at a time.

Users read ~`rate` keys/s (Poisson, drifting slowly), with a skewed popularity. Each read
goes to the cache server your `Router.node_for(key)` picks; a hit answers at once, a miss
goes to the database (10 ms a read, 4 at a time, a queue of 400, then it refuses) and then
fills that server's cache (an LRU of 1,500 keys per server).

Incidents change the cluster, like in production: a node dies and is replaced later with
an empty cache, the autoscaler adds a node for a while, or a deploy restarts one. The
first one is always a node dying at 0:20. Every change is measured right where it
happens: the scenario asks your router where 2,000 sample keys go before and after it.

The run never restarts: caches, the database queue and your router carry on from one
minute to the next. It starts warm (a warm-up runs before 0:00).
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_left
from collections import OrderedDict
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.services import DatabaseBusy, SlowDatabase
from core.vtime import VirtualRun, now
from labs.consistent_hashing import lab

LAB = "consistent_hashing"
NAMES = ("Router",)
PIECE = 60.0
DRAIN = 10.0
WARMUP = 30.0
KEYS = 20_000
SKEW = 0.9
SAMPLE = 2_000  # keys checked before and after each change
CACHE = 1_500  # keys per cache server (LRU)
TICK = 0.005  # reads closer together than this are handled in one go
SLOTS = [f"c{i}" for i in range(lab.SLOTS)]
SPARE = SLOTS[-1]  # the node the autoscaler adds

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 32.0, "crash", 1.0, "kernel_panic")
KINDS = [
    Kind("crash", 0.45, median=12.0, shortest=6.0, longest=25.0,
         causes=("kernel_panic", "spot_reclaimed", "oom_killed", "disk_full")),
    Kind("scale", 0.35, median=18.0, shortest=10.0, longest=30.0,
         causes=("evening_peak", "sale_capacity", "autoscaler_cpu")),
    Kind("deploy", 0.20, median=6.0, shortest=4.0, longest=10.0,
         causes=("rolling_deploy", "config_restart", "kernel_patch")),
]
MEAN_GAP = 30.0
QUIET = 26.0  # calm after a change: its 8 s are judged, then 15 s of calm before the next


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, seed: int) -> str:
    """The node an incident takes away (or adds): the same one every time for a seed."""
    if inc.kind == "scale":
        return SPARE
    return random.Random(f"{seed}:{inc.t0}:victim").choice(SLOTS[:lab.BASE_NODES])


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.live = SLOTS[:lab.BASE_NODES]
        self.router = None  # built in boot(), inside the simulation
        self.index = {n: i for i, n in enumerate(SLOTS)}
        self.caches: dict[str, OrderedDict] = {n: OrderedDict() for n in SLOTS}
        self.db = SlowDatabase(service_time=0.010, concurrency=4, queue_limit=400)
        weights = itertools.accumulate(1.0 / (k ** SKEW) for k in range(1, KEYS + 1))
        self.cum = list(weights)
        self.sample = [f"k{i}" for i in range(0, KEYS, KEYS // SAMPLE)]
        self.reads: list[tuple] = []  # (start, slot, hit, end, ok)
        self.changes: list[tuple] = []  # (t, op, slot, moved, ideal, imbalance, counts, members)
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, float] = {}
        self._ids = itertools.count()

    # ---- your router, checked

    def route(self, key: str) -> str:
        node = self.router.node_for(key)
        if node not in self.live:
            raise ValueError(lab_text(LAB).STRINGS["bad_node"].format(node=node, live=", ".join(self.live)))
        return node

    def snapshot(self, op: str, node: str | None, before: dict[str, str] | None) -> None:
        after = {k: self.route(k) for k in self.sample}
        counts = [0] * len(SLOTS)
        for n in after.values():
            counts[self.index[n]] += 1
        live_counts = [counts[self.index[n]] for n in self.live]
        imbalance = max(live_counts) / (sum(live_counts) / len(live_counts))
        moved = sum(before[k] != after[k] for k in self.sample) / len(self.sample) if before else 0.0
        ideal = 1.0 / max(len(self.live), len(self.live) + (1 if op == "remove" else -1 if op == "add" else 0))
        self.changes.append((now(), op, self.index[node] if node else -1, moved, ideal, imbalance,
                             tuple(counts), tuple(n in self.live for n in SLOTS)))

    def change(self, op: str, node: str) -> None:
        before = {k: self.route(k) for k in self.sample}
        if op == "remove":
            self.live = [n for n in self.live if n != node]
            self.router.remove(node)
        else:
            self.live = sorted(self.live + [node], key=self.index.get)
            self.router.add(node)
        self.caches[node] = OrderedDict()  # a node that leaves or joins has an empty cache
        self.snapshot(op, node, before)

    # ---- the simulation

    async def boot(self) -> None:
        self.router = self.code.Router(list(self.live))

    async def read(self, key: str, node: str, start: float, rid: int) -> None:
        self.open[rid] = start
        try:
            value = await self.db.read(key)
            ok = True
        except DatabaseBusy:
            value, ok = None, False
        finally:
            self.open.pop(rid, None)
        if ok and node in self.live:
            cache = self.caches[node]
            cache[key] = value
            if len(cache) > CACHE:
                cache.popitem(last=False)
        if start >= 0:
            self.reads.append((start, self.index[node], False, max(start, now()), ok))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        total = self.cum[-1]
        while self.router is None:
            await asyncio.sleep(0)
        for t in arrivals(self.rate, self.seed, -WARMUP, rng):
            if t - now() > TICK:  # reads a few ms apart are handled together: fewer loop turns
                await asyncio.sleep(t - now())
            key = f"k{bisect_left(self.cum, rng.random() * total)}"
            try:
                node = self.route(key)
            except Exception as exc:  # noqa: BLE001 - a bug in your router: surface it
                self.bugs.append(exc)
                return
            cache = self.caches[node]
            if key in cache:
                cache.move_to_end(key)
                if t >= 0:
                    self.reads.append((t, self.index[node], True, t + 0.001, True))
            else:
                asyncio.ensure_future(self.read(key, node, t, next(self._ids)))

    async def chaos(self) -> None:
        while self.router is None:
            await asyncio.sleep(0)
        await asyncio.sleep(0 - now())
        self.snapshot("start", None, None)
        for inc in incidents(self.seed):
            self.planned.append(inc)
            node = victim(inc, self.seed)
            await asyncio.sleep(inc.t0 - now())
            self.guard(lambda: self.change("add" if inc.kind == "scale" else "remove", node))
            await asyncio.sleep(inc.t1 - now())
            self.guard(lambda: self.change("remove" if inc.kind == "scale" else "add", node))

    def guard(self, fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a bug in your router: surface it
            self.bugs.append(exc)


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 500.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun(start=-WARMUP)
    s = _Sim(code, seed, rate)
    for coro in (s.boot(), s.traffic(), s.chaos()):
        sim.spawn(coro)
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
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    # (start, slot, hit, end, ok)
                    "reads": _take(s.reads, 0, a, b),
                    # (t, op, slot, moved, ideal, imbalance, counts per slot, live per slot)
                    "changes": _take(s.changes, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
