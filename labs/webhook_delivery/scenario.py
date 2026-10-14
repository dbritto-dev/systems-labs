"""Lab webhook_delivery: one endless run on virtual time, handed out a minute at a time.

A shop platform sends webhooks to 20 customer endpoints: every order makes order.created, then
order.paid (0.05-2 s later), order.fulfilled (4-15 s later) and sometimes order.refunded (15-40 s
later), ~60 events a second in all; big customers get more than small ones. WORKERS delivery
workers ask your `Dispatcher.next(now)` what to send, POST it and report back with
`Dispatcher.done(ev, status, now)`. A healthy endpoint answers 200 in ~60 ms (and 1 time in 300
a stray 502).

Incidents come at random, like in production: an endpoint goes DOWN (their deploy answers 503,
an expired TLS certificate, a crash loop refusing connections), its connections HANG (a DNS
change points at an old IP, a firewall drops packets: no answer until the timeout), it gets
SLOW (their database is struggling: 2.5-8 s per answer), it answers 500 forever to a few
malformed events (POISON), or a sale makes a BURST of 2-3x the events. The first incident is
always endpoint #1 (the biggest customer) hanging at 0:20-0:45.

The run never restarts: the dispatcher, its queues and the clock carry on from minute to minute.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.webhook_delivery.api import CLIENT_TIMEOUT, ENDPOINTS, TYPES, WORKERS, Event, ok

LAB = "webhook_delivery"
NAMES = ("Dispatcher",)
PIECE = 60.0
DRAIN = CLIENT_TIMEOUT + 1.0  # simulate this far past a minute: every attempt started in it has ended
SAMPLE = 0.5  # how often the backlog is recorded
POLL = 0.05  # an idle worker asks again this often (for retries that come due)

EVENTS_PER_ORDER = 3.15  # created, paid, fulfilled, and 15% refunded
REFUNDED = 0.15
LATENCY = 0.06  # median seconds a healthy endpoint takes to answer
STRAY_502 = 1 / 300  # a healthy endpoint's load balancer answers 502 now and then
SLOW = (2.5, 8.0)  # seconds a slow endpoint takes to answer
POISON_SHARE = 0.05  # share of an endpoint's new events that are malformed during a poison incident
BURST_MAX = 3.0
WEIGHTS = [1 / (i + 1) ** 0.7 for i in range(ENDPOINTS)]  # endpoint #1 is the biggest customer

# Causes are keys; their words are in text/<lang>.py (CAUSES). An endpoint incident's severity is the
# endpoint (0-9: the bigger customers), a burst's the traffic multiplier.
FIRST = Planned(20.0, 45.0, "hang", 0.0, "dns")
KINDS = [
    Kind("down", 0.3, median=40.0, shortest=15.0, longest=120.0, severity=(0.0, 9.99),
         causes=("deploy", "cert_expired", "maintenance", "crashloop")),
    Kind("hang", 0.2, median=30.0, shortest=15.0, longest=90.0, severity=(0.0, 9.99),
         causes=("dns", "firewall", "allowlist", "no_backends")),
    Kind("slow", 0.2, median=30.0, shortest=15.0, longest=60.0, severity=(0.0, 9.99),
         causes=("database", "sync_calls", "table_lock", "swapping")),
    Kind("poison", 0.15, median=20.0, shortest=10.0, longest=40.0, severity=(0.0, 9.99),
         causes=("emoji", "null_field", "currency", "big_payload")),
    Kind("burst", 0.15, median=25.0, shortest=15.0, longest=45.0, severity=(2.0, BURST_MAX),
         causes=("flash_sale", "black_friday", "bulk_import", "newsletter")),
]
ENDPOINT_KINDS = ("down", "hang", "slow", "poison")
DOWN_STATUS = {"deploy": 503, "maintenance": 503, "cert_expired": None, "crashloop": None}
POISON_STATUS = {"emoji": 500, "null_field": 500, "currency": 500, "big_payload": 413}
MEAN_GAP = 25.0
QUIET = 50.0  # calm after an incident: 15 s of baseline before the next + time for retries to land


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def endpoint_of(severity: float) -> int:
    """The endpoint an incident hits (its severity)."""
    return int(severity)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code = code
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 7 + 3)
        self.dispatcher = code.Dispatcher(self.give_up, random.Random(seed * 11 + 1))
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.idle: deque[asyncio.Future] = deque()
        self.ids = itertools.count()
        self.keys = itertools.count(1)
        # The endpoints right now.
        self.mode: list[str | None] = [None] * ENDPOINTS  # None (healthy), "down", "hang", "slow"
        self.down_status: list[int | None] = [503] * ENDPOINTS
        self.poison_at: int = -1  # the endpoint getting malformed events, if any
        self.poison_status = 500
        self.burst = 1.0
        # What happened to each event.
        self.poison: set[int] = set()
        self.delivered: set[int] = set()
        self.gone: set[int] = set()  # given up
        self.pending_seqs: dict[int, set[int]] = {}  # key -> seqs made and neither delivered nor given up
        self.pending = [0] * ENDPOINTS
        self.busy = 0
        # Rows handed out.
        self.events: list[tuple] = []  # (created, id, endpoint, key, seq, poison)
        self.attempts: list[tuple] = []  # (start, id, endpoint, end, status or -1, ok, attempt, worker)
        self.deliveries: list[tuple] = []  # (t, id, endpoint, created, out of order, attempts)
        self.gave_up: list[tuple] = []  # (t, id, endpoint, created, poison)
        self.samples: list[tuple] = []  # (t, busy workers, pending, pending per endpoint)

    # ---- your code, guarded: a bug is surfaced, never swallowed

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:  # a bug in the code under test
            self.bugs.append(exc)
            return None

    def give_up(self, ev: Event) -> None:
        """The dispatcher gives up on an event: it is never delivered."""
        if ev.id in self.delivered or ev.id in self.gone:
            return
        self.gone.add(ev.id)
        self._settle(ev)
        self.gave_up.append((now(), ev.id, ev.endpoint, ev.created, ev.id in self.poison))

    def _settle(self, ev: Event) -> bool:
        """The event is delivered or given up: True if an earlier event of its order is still pending."""
        self.pending[ev.endpoint] -= 1
        seqs = self.pending_seqs.get(ev.key)
        if seqs is None:
            return False
        seqs.discard(ev.seq)
        early = any(s < ev.seq for s in seqs)
        if not seqs:
            del self.pending_seqs[ev.key]
        return early

    # ---- the shop makes events

    def emit(self, key: int, endpoint: int, seq: int) -> None:
        ev = Event(next(self.ids), endpoint, key, seq, TYPES[seq - 1], now())
        poison = endpoint == self.poison_at and self.rng.random() < POISON_SHARE
        if poison:
            self.poison.add(ev.id)
        self.pending_seqs.setdefault(key, set()).add(seq)
        self.pending[endpoint] += 1
        self.events.append((ev.created, ev.id, endpoint, key, seq, poison))
        self._call(self.dispatcher.submit, ev, now())
        self.poke()

    async def orders(self) -> None:
        rng = random.Random(self.seed * 7)
        loop = asyncio.get_running_loop()
        base = self.rate / EVENTS_PER_ORDER
        for t in arrivals(base * BURST_MAX, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            if rng.random() * BURST_MAX > self.burst:
                continue  # thinning: only a burst gets every arrival
            key = next(self.keys)
            endpoint = rng.choices(range(ENDPOINTS), WEIGHTS)[0]
            self.emit(key, endpoint, 1)
            loop.call_at(t + rng.uniform(0.05, 2.0), self.emit, key, endpoint, 2)
            loop.call_at(t + rng.uniform(4.0, 15.0), self.emit, key, endpoint, 3)
            if rng.random() < REFUNDED:
                loop.call_at(t + rng.uniform(15.0, 40.0), self.emit, key, endpoint, 4)

    # ---- the endpoints answer

    def answer(self, ev: Event, timeout: float) -> tuple[float, int | None]:
        """(seconds the POST takes, status or None) for this attempt."""
        mode = self.mode[ev.endpoint]
        rng = self.rng
        if mode == "down":
            seconds, status = rng.uniform(0.01, 0.05), self.down_status[ev.endpoint]
        elif mode == "hang":
            seconds, status = math.inf, None
        elif mode == "slow":
            seconds, status = rng.uniform(*SLOW), 200
        elif rng.random() < STRAY_502:
            seconds, status = 0.02, 502
        else:
            seconds = min(1.5, max(0.015, LATENCY * math.exp(0.6 * rng.gauss(0, 1))))
            status = self.poison_status if ev.id in self.poison else 200
        if seconds > timeout:
            return timeout, None
        return seconds, status

    # ---- the delivery workers

    def poke(self) -> None:
        """Wake one idle worker: there may be something to send."""
        while self.idle:
            f = self.idle.popleft()
            if not f.done():
                f.set_result(None)
                return

    async def worker(self, slot: int) -> None:
        loop = asyncio.get_running_loop()
        d = self.dispatcher
        while True:
            ev = self._call(d.next, now())
            if not isinstance(ev, Event):
                fut = loop.create_future()
                self.idle.append(fut)
                await fut
                continue
            self.poke()  # one more worker looks: more may be ready
            timeout = getattr(d, "timeout", None)
            if not isinstance(timeout, (int, float)) or not 0 < timeout <= CLIENT_TIMEOUT:
                timeout = CLIENT_TIMEOUT
            ev.attempts += 1
            start = now()
            seconds, status = self.answer(ev, timeout)
            self.busy += 1
            try:
                await asyncio.sleep(seconds)
            finally:
                self.busy -= 1
            good = ok(status)
            self.attempts.append((start, ev.id, ev.endpoint, now(), -1 if status is None else status, good,
                                  ev.attempts, slot))
            if good and ev.id not in self.delivered and ev.id not in self.gone:
                self.delivered.add(ev.id)
                early = self._settle(ev)
                self.deliveries.append((now(), ev.id, ev.endpoint, ev.created, early, ev.attempts))
            self._call(d.done, ev, status, now())
            ev = None

    async def ticker(self) -> None:
        while True:
            await asyncio.sleep(POLL)
            self.poke()

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            ep = endpoint_of(inc.severity)
            match inc.kind:
                case "down":
                    self.mode[ep] = "down"
                    self.down_status[ep] = DOWN_STATUS[inc.cause]
                case "hang" | "slow":
                    self.mode[ep] = inc.kind
                case "poison":
                    self.poison_at = ep
                    self.poison_status = POISON_STATUS[inc.cause]
                case "burst":
                    self.burst = inc.severity
            await asyncio.sleep(max(0.0, inc.t1 - now()))
            self.mode = [None] * ENDPOINTS
            self.poison_at, self.burst = -1, 1.0  # malformed events stay malformed: they fail forever

    async def sampler(self) -> None:
        while True:
            self.samples.append((now(), self.busy, sum(self.pending), tuple(self.pending)))
            await asyncio.sleep(SAMPLE)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 60.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for slot in range(WORKERS):
        sim.spawn(s.worker(slot))
    sim.spawn(s.orders())
    sim.spawn(s.chaos())
    sim.spawn(s.ticker())
    sim.spawn(s.sampler())
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
                    # (created, id, endpoint, key, seq, poison)
                    "events": s.take(s.events, 0, a, b),
                    # (start, id, endpoint, end, status or -1 for no answer, ok, attempt, worker)
                    "attempts": s.take(s.attempts, 0, a, b),
                    # (t, id, endpoint, created, out of order, attempts)
                    "delivered": s.take(s.deliveries, 0, a, b),
                    # (t, id, endpoint, created, poison)
                    "gaveup": s.take(s.gave_up, 0, a, b),
                    # (t, busy workers, pending, pending per endpoint)
                    "samples": s.take(s.samples, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 60.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
