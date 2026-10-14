"""Lab deadlock_avoidance: one endless run on virtual time, handed out a minute at a time.

Customers pay merchants ~`rate` times a second through one payments service, which runs at most
`WORKERS` transfers at once (its database connections); the rest wait at the door. Every transfer
locks both accounts, moves the money and writes the audit log. A few accounts are hot: the
marketplace's escrow and fee accounts, and four big merchants (a Zipf share of all payments).
Merchants also refund now and then, and pay their commission to the fee account.

Incidents come at random, like in production: a payout run (many transfers among the hot accounts,
in both directions, and out to sellers), a burst of refunds (a merchant refunds the same buyers who
keep paying it: transfers against the normal direction), a slow audit log (a few writes stall for
0.2-0.6 s, whoever holds locks while writing), or a batch job (a fee sweep locks 10-25 accounts at
once). The first incident is always a payout run at 0:20-0:30.

The lock manager has no deadlock detector: the scenario has one (it looks for cycles in the
wait-for graph every 0.1 s) only to report them. A client gives up after `DEADLINE` seconds; the
server kills a transaction that has run for `TXN_LIMIT` seconds, which is what ends a deadlock when
your code does not.

The run never restarts: balances, locks and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from bisect import bisect_left
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.deadlock_avoidance.api import Audit, Ledger, LockManager, LockTimeout, Request, current_request

LAB = "deadlock_avoidance"
NAMES = ("Payments", "LOCK_TIMEOUT", "backoff", "lock_order")
PIECE = 60.0
WORKERS = 64  # transfers the service runs at once
DEADLINE = 2.0  # seconds a client waits for its answer
TXN_LIMIT = 8.0  # seconds before the server kills a transaction (and its locks go)
DRAIN = DEADLINE + TXN_LIMIT + 1.0  # simulate this far past a minute before handing it out
SAMPLE = 0.1  # seconds between looks at the wait-for graph

ESCROW, FEES = 1, 2
MERCHANTS = list(range(3, 53))  # 3..6 are the four big ones
HOT = [ESCROW, FEES, 3, 4, 5, 6]
CUSTOMERS = list(range(100, 5100))
SKEW = 1.0  # Zipf exponent of the merchants' popularity
REFUNDS, COMMISSIONS = 0.03, 0.03  # shares of normal traffic
CROWD = 80  # buyers in a refund burst
PAYOUT_AUDIT = 1.0  # a payout run fills the audit log: every audit write takes this many times longer

# What a transfer is.
PAYMENT, REFUND, COMMISSION, PAYOUT, BATCH = range(5)
# How it ended for its client.
OK, FAILED, TIMEOUT = range(3)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "payout", 85.0, "month_end")
KINDS = [
    Kind("payout", 0.3, median=10.0, shortest=6.0, longest=20.0, severity=(50.0, 90.0),
         causes=("month_end", "weekly_payout", "instant_payouts", "reserve_release")),
    Kind("refunds", 0.25, median=10.0, shortest=6.0, longest=20.0, severity=(25.0, 45.0),
         causes=("cancelled_sale", "double_charge", "event_cancelled", "chargebacks")),
    Kind("slow", 0.25, median=10.0, shortest=6.0, longest=20.0, severity=(0.4, 0.8),
         causes=("audit_disk", "audit_failover", "audit_compaction", "audit_backup")),
    Kind("batch", 0.2, median=12.0, shortest=6.0, longest=20.0, severity=(2.0, 5.0),
         causes=("fee_sweep", "interest", "reconciliation", "fx_settlement")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: 5 s for the last transfers, 15 s of baseline before the next


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.rng = random.Random(seed * 13 + 1)
        self.cum = list(itertools.accumulate(1.0 / (k ** SKEW) for k in range(1, len(MERCHANTS) + 1)))
        self.locks = LockManager(random.Random(seed * 13 + 2), self.on_wait)
        self.ledger = Ledger(HOT + MERCHANTS[4:] + CUSTOMERS, random.Random(seed * 13 + 3))
        self.audit = Audit(self.locks, random.Random(seed * 13 + 4))
        self.app = code.Payments(self.locks, self.ledger, self.audit, random.Random(seed * 13 + 5))
        self.total = self.ledger.total()
        self.free = WORKERS
        self.door: list[asyncio.Future] = []  # transfers waiting for a worker
        self.ids = itertools.count()
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, tuple[float, asyncio.Task]] = {}  # running rid -> (got a worker, task)
        self.transfers: list[tuple] = []  # (id, start, end, ok, done, kind, src, dst, outcome, tries, wait)
        self.waits: list[tuple] = []  # (t0, t1, id, held, want, result)
        self.cycles: list[tuple] = []  # (t0, t1, accounts)
        self.samples: list[tuple] = []  # (t, busy, at the door, waiting for a lock, drift, deadlocks now)
        self.alive: dict[frozenset, list] = {}  # deadlocks seen in the last sample: ids -> [t0, accounts]

    def merchant(self, rng: random.Random) -> int:
        return MERCHANTS[min(len(MERCHANTS) - 1, bisect_left(self.cum, rng.random() * self.cum[-1]))]

    def on_wait(self, t0, t1, rid, held, want, result) -> None:
        if t0 >= 0:
            self.waits.append((t0, t1, rid, held, want, result))

    # ---- traffic

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 13)
        for t in arrivals(self.rate, self.seed, 0.0, rng):
            await asyncio.sleep(t - now())
            r = rng.random()
            amount = rng.randint(100, 20_000)
            if r < REFUNDS:
                self.go(REFUND, self.merchant(rng), rng.choice(CUSTOMERS), amount)
            elif r < REFUNDS + COMMISSIONS:
                self.go(COMMISSION, self.merchant(rng), FEES, amount // 10)
            else:
                self.go(PAYMENT, rng.choice(CUSTOMERS), self.merchant(rng), amount)

    def go(self, kind: int, src: int, dst, amount) -> None:
        asyncio.ensure_future(self.serve(kind, src, dst, amount))

    async def serve(self, kind: int, src: int, dst, amount) -> None:
        rid = next(self.ids)
        start = now()
        if self.free:
            self.free -= 1
        else:  # wait at the door for a worker
            fut = asyncio.get_running_loop().create_future()
            self.door.append(fut)
            await fut
        if now() - start >= DEADLINE:  # the client has given up already: do not start it
            self.done_worker()
            self.record(rid, start, now(), kind, src, dst, TIMEOUT, 0, 0.0)
            return
        req = Request(rid)
        current_request.set(req)
        self.open[rid] = (now(), asyncio.current_task())
        outcome = OK
        try:
            if kind == BATCH:
                await self.app.settle(dst)
            else:
                await self.app.transfer(src, dst, amount)
        except LockTimeout:
            outcome = FAILED  # it gave up
        except asyncio.CancelledError:
            outcome = TIMEOUT  # killed by the server
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            outcome = FAILED
        finally:
            self.open.pop(rid, None)
            self.locks.release_request(rid)  # the transaction ends: its locks go
            self.done_worker()
        self.record(rid, start, now(), kind, src, dst, outcome, req.tries, req.wait)

    def done_worker(self) -> None:
        while self.door:
            fut = self.door.pop(0)
            if not fut.done():
                fut.set_result(None)
                return
        self.free += 1

    def record(self, rid, start, done, kind, src, dst, outcome, tries, wait) -> None:
        if start < 0:
            return
        end = min(done, start + DEADLINE)
        if done - start > DEADLINE:
            outcome = TIMEOUT
        if kind == BATCH:
            src, dst = FEES, len(dst)
        self.transfers.append((rid, start, end, outcome == OK, done, kind, src, dst, outcome, tries, wait))

    # ---- incidents

    async def stream_of(self, rate: float, until: float, make) -> None:
        rng = random.Random(self.seed * 17 + int(now() * 10))
        t = now()
        while True:
            t += rng.expovariate(rate)
            if t >= until:
                return
            await asyncio.sleep(t - now())
            make(rng)

    def payout(self, rng: random.Random) -> None:
        amount = rng.randint(1_000, 50_000)
        if rng.random() < 0.6:  # among the hot accounts, either way
            a, b = rng.sample(HOT, 2)
            self.go(PAYOUT, a, b, amount)
        else:  # out to a seller
            self.go(PAYOUT, rng.choice((ESCROW, 3, 4, 5, 6)), rng.choice(CUSTOMERS), amount)

    def refund_burst(self, rng: random.Random, merchant: int, crowd: list[int]) -> None:
        self.go(REFUND, merchant, rng.choice(crowd), rng.randint(100, 20_000))
        self.go(PAYMENT, rng.choice(crowd), merchant, rng.randint(100, 20_000))  # they keep buying

    def batch(self, rng: random.Random) -> None:
        merchants = []
        for _ in range(rng.randint(10, 25)):
            m = self.merchant(rng)
            if m not in merchants:
                merchants.append(m)
        fees = [(m, -rng.randint(100, 5_000)) for m in merchants]  # in the job's order
        self.go(BATCH, FEES, fees + [(FEES, -sum(d for _, d in fees))], None)

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            rng = random.Random(self.seed * 23 + int(inc.t0))
            match inc.kind:
                case "payout":
                    self.audit.busy = PAYOUT_AUDIT
                    self.ensure(self.stream_of(inc.severity, inc.t1, self.payout))
                case "refunds":
                    merchant, crowd = rng.choice(HOT[2:]), rng.sample(CUSTOMERS, CROWD)
                    self.ensure(self.stream_of(inc.severity, inc.t1,
                                               lambda r: self.refund_burst(r, merchant, crowd)))
                case "slow":
                    self.audit.slow = inc.severity / 100
                case "batch":
                    self.ensure(self.stream_of(inc.severity, inc.t1, self.batch))
            await asyncio.sleep(inc.t1 - now())
            self.audit.slow, self.audit.busy = 0.0, 1.0

    def ensure(self, coro) -> None:
        asyncio.ensure_future(coro)

    # ---- the detector (only to report), and the server's transaction timeout

    async def watch(self) -> None:
        k = 0
        while True:
            k += 1
            await asyncio.sleep(k * SAMPLE - now())
            t = now()
            found = {frozenset(ids): accounts for ids, accounts in self.locks.cycles()}
            for key in [key for key in self.alive if key not in found]:
                t0, accounts = self.alive.pop(key)
                self.cycles.append((t0, t, accounts))
            for key, accounts in found.items():
                self.alive.setdefault(key, [t, accounts])
            busy = WORKERS - self.free
            waiting = len(self.locks.waiting)
            drift = self.ledger.drift
            self.samples.append((t, busy, len(self.door), waiting, drift, len(found)))
            if k % 5 == 0:
                for rid, (t0, task) in list(self.open.items()):
                    if t - t0 >= TXN_LIMIT:
                        task.cancel()

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 200.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun(0.0)
    s = _Sim(code, seed, rate)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    sim.spawn(s.watch())
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
                    # (id, start, end, ok, done, kind, src, dst, outcome, tries, wait)
                    "transfers": s.take(s.transfers, 1, a, b),
                    "waits": s.take(s.waits, 0, a, b),  # (t0, t1, id, held, want, result)
                    "cycles": s.take(s.cycles, 0, a, b),  # (t0, t1, accounts)
                    "samples": s.take(s.samples, 0, a, b),  # (t, busy, door, waiting, drift, deadlocks)
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 200.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
