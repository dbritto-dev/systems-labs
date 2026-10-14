"""Lab hot_partition: one endless run on virtual time, handed out a minute at a time.

Users like, click and view things: ~`rate` operations a second on counters (60% reads of a
count, 40% increments), over 5,000 keys with a Zipf-like popularity. Every operation goes
through your `Counters` (an increment is `incr(key)`, a read is `read(key)`) to a store of six
partitions, each serving 100 requests a second (see api.py).

Incidents come at random, like in production: one key explodes. A celebrity's post goes viral
(likes: increments), a link in a newsletter is clicked by everyone (increments), a flash sale
sells one product (increments of its units sold, and its page reads the count), or a bot
hammers one id (reads). Its traffic ramps up in 1.5 s, holds, then falls to a tail that stays
for a minute. The first incident is always a viral post at 0:20-0:32.

The run never restarts: the store's counters, your Counters and the clock carry on from minute
to minute.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from bisect import bisect_left
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.hot_partition import lab
from labs.hot_partition.api import CURRENT, PARTITIONS, SERVICE, Op, Store, Throttled, base_of, home

LAB = "hot_partition"
NAMES = ("Counters",)
PIECE = 60.0
DRAIN = 5.0  # simulate this far past a minute before handing it out
STUCK = 20.0  # an operation still running after this long is a bug
KEYS = 5_000
SKEW = 0.9
WRITE_SHARE = 0.4  # of the usual traffic
TICK = 0.004  # operations closer together than this start together
SAMPLE = 0.25  # how often the partitions' load is recorded
AUDIT = 0.5  # how often the hot key's count is checked against what was acknowledged
RAMP_UP = 1.5
RAMP_DOWN = 2.0
TAIL_FOR = 60.0  # seconds the tail lasts after an incident
TAIL_TAU = 30.0  # ... decaying like this

# Each kind of hot key: the share of its operations that are reads during the incident, and its
# tail after it (writes/s and reads/s, as shares of the peak).
PROFILE = {
    "viral": (0.08, 0.04, 0.07),
    "link": (0.03, 0.05, 0.02),
    "sale": (0.5, 0.04, 0.08),
    "bot": (1.0, 0.0, 0.03),
}
PREFIX = {"viral": "post", "link": "link", "sale": "item", "bot": "item"}

# Op results (ops table) and what a store request was for (reqs table: api.PLAIN, HOT, FAN, FOLD).
OK, THROTTLED = 1, 0

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 32.0, "viral", 240.0, "celebrity_post")
KINDS = [
    Kind("viral", 0.3, median=12.0, shortest=8.0, longest=20.0, severity=(200.0, 340.0),
         causes=("celebrity_post", "viral_video", "live_vote", "breaking_news")),
    Kind("link", 0.2, median=9.0, shortest=5.0, longest=15.0, severity=(200.0, 320.0),
         causes=("newsletter", "push_notification", "homepage", "influencer")),
    Kind("sale", 0.25, median=14.0, shortest=8.0, longest=22.0, severity=(200.0, 340.0),
         causes=("flash_sale", "ticket_drop", "limited_sneaker", "price_glitch")),
    Kind("bot", 0.25, median=10.0, shortest=6.0, longest=18.0, severity=(200.0, 400.0),
         causes=("scraper", "retry_loop", "health_check", "load_test")),
]
MEAN_GAP = 25.0
QUIET = lab.AFTER_END + 6.0  # calm after an incident: its after-window is judged before the next


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def hot_key(inc: Planned, seed: int) -> str:
    """The key that explodes in an incident: a new one each time, the same for a seed."""
    n = random.Random(f"{seed}:{inc.t0}:key").randrange(100_000, 1_000_000)
    return f"{PREFIX[inc.kind]}:{n}"


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.rng = random.Random(seed * 13 + 5)
        self.hot: dict[str, int] = {}  # incident keys -> incident index
        self.store = Store(on_request=self.on_request, hot_index=lambda key: self.hot.get(base_of(key)[0], -1))
        self.client = None  # built in boot(), inside the simulation
        weights = itertools.accumulate(1.0 / (k ** SKEW) for k in range(1, KEYS + 1))
        self.cum = list(weights)
        self.keys = [f"post:{i}" for i in range(KEYS)]
        self.sent: dict[str, int] = {}
        self.acked: dict[str, int] = {}
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.ops: list[tuple] = []  # (start, end, write, ok, requests, hot)
        self.reqs: list[tuple] = []  # (t, partition, kind, ok, incident whose key it is or -1)
        self.load: list[tuple] = []  # (t, busy per partition, requests per partition, throttled per partition)
        self.audits: list[tuple] = []  # (t, incident, acked, stored, sent)
        self.hots: list[tuple] = []  # (t0, incident, key, partition)
        self.running: dict[Op, float] = {}  # operations in progress -> when they started
        self.busy = [0.0] * PARTITIONS
        self.count = [0] * PARTITIONS
        self.refused = [0] * PARTITIONS

    # ---- the store tells us every request

    def on_request(self, t: float, p: int, kind: int, ok: bool, hot: int) -> None:
        if ok:
            self.busy[p] += SERVICE
            self.count[p] += 1
        else:
            self.refused[p] += 1
        self.reqs.append((t, p, kind, ok, hot))

    # ---- one user operation, through your Counters

    async def op(self, key: str, write: bool, hot: bool) -> None:
        o = Op()
        CURRENT.set(o)
        start = now()
        self.running[o] = start
        ok = OK
        try:
            if write:
                self.sent[key] = self.sent.get(key, 0) + 1
                await self.client.incr(key)
                self.acked[key] = self.acked.get(key, 0) + 1
            else:
                await self.client.read(key)
        except Throttled:
            ok = THROTTLED
        except Exception as exc:  # noqa: BLE001 - a bug in the code under test: surface it
            self.bugs.append(exc)
        o.done = True
        del self.running[o]
        self.ops.append((start, now(), write, ok, o.requests, hot))

    def launch(self, key: str, write: bool, hot: bool) -> None:
        asyncio.get_running_loop().create_task(self.op(key, write, hot))

    async def boot(self) -> None:
        self.client = self.code.Counters(self.store, random.Random(self.seed * 3 + 1))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        total = self.cum[-1]
        while self.client is None:
            await asyncio.sleep(0)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            if t - now() > TICK:  # operations a few ms apart start together: fewer loop turns
                await asyncio.sleep(t - now())
            key = self.keys[bisect_left(self.cum, rng.random() * total)]
            self.launch(key, rng.random() < WRITE_SHARE, False)

    async def burst(self, inc: Planned, key: str) -> None:
        """One key's traffic: up in RAMP_UP, flat until t1, down in RAMP_DOWN, then a tail."""
        rng = random.Random(f"{self.seed}:{inc.t0}:burst")
        reads, tail_w, tail_r = PROFILE[inc.kind]
        peak = inc.severity

        def level(t: float) -> float:
            if t < inc.t0 + RAMP_UP:
                return max(0.0, (t - inc.t0) / RAMP_UP)
            return 1.0

        t = inc.t0
        while True:  # the incident itself
            t += rng.expovariate(peak)
            if t >= inc.t1:
                break
            if t - now() > TICK:
                await asyncio.sleep(t - now())
            if rng.random() < level(t):
                self.launch(key, rng.random() >= reads, True)
        tail = peak * (tail_w + tail_r)
        end = inc.t1 + TAIL_FOR

        def rate_at(t: float) -> float:
            if t < inc.t1 + RAMP_DOWN:
                return peak + (tail - peak) * (t - inc.t1) / RAMP_DOWN
            return tail * math.exp(-(t - inc.t1 - RAMP_DOWN) / TAIL_TAU)

        t, top = inc.t1, peak
        while tail > 0:
            t += rng.expovariate(top)
            if t >= end:
                break
            if t >= inc.t1 + RAMP_DOWN:
                top = tail
            if t - now() > TICK:
                await asyncio.sleep(t - now())
            r = rate_at(t)
            if rng.random() * top < r:
                share = tail_r / (tail_w + tail_r) if t >= inc.t1 + RAMP_DOWN else reads
                self.launch(key, rng.random() >= share, True)

    async def chaos(self) -> None:
        while self.client is None:
            await asyncio.sleep(0)
        for k, inc in enumerate(incidents(self.seed)):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            key = hot_key(inc, self.seed)
            self.hot[key] = k
            self.hots.append((inc.t0, k, key, home(key)))
            asyncio.ensure_future(self.burst(inc, key))
            asyncio.ensure_future(self.auditor(inc, k, key))
            await asyncio.sleep(max(0.0, inc.t1 - now()))

    async def auditor(self, inc: Planned, k: int, key: str) -> None:
        """Every AUDIT s, add up what the store holds in every key your keys_of(key) names."""
        end = inc.t1 + lab.AFTER_END + 2 * AUDIT
        while now() <= end:
            try:
                names = list(self.client.keys_of(key))
                stored = sum(self.store.peek(n) for n in names)
            except Exception as exc:  # noqa: BLE001 - a bug in keys_of: surface it
                self.bugs.append(exc)
                return
            self.audits.append((now(), k, self.acked.get(key, 0), stored, self.sent.get(key, 0)))
            await asyncio.sleep(AUDIT)

    async def sampler(self) -> None:
        while True:
            await asyncio.sleep(SAMPLE)
            busy = tuple(min(1.0, b / SAMPLE) for b in self.busy)
            self.load.append((now() - SAMPLE, busy, tuple(self.count), tuple(self.refused)))
            self.busy = [0.0] * PARTITIONS
            self.count = [0] * PARTITIONS
            self.refused = [0] * PARTITIONS


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 120.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for coro in (s.boot(), s.traffic(), s.chaos(), s.sampler()):
        sim.spawn(coro)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(t < b + DRAIN - STUCK for t in s.running.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    # (start, end, write, ok, store requests, hot key)
                    "ops": _take(s.ops, 0, a, b),
                    # (t, partition, kind, ok, incident whose key it is or -1): every request to a partition
                    "reqs": _take(s.reqs, 0, a, b),
                    # (t, busy share per partition, requests per partition, throttled per partition)
                    "load": _take(s.load, 0, a, b),
                    # (t, incident, acked, stored, sent)
                    "audits": _take(s.audits, 0, a, b),
                    # (t0, incident, key, home partition)
                    "hots": _take(s.hots, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
