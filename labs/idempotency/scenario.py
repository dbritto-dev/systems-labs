"""Lab idempotency: one endless run on virtual time, handed out a minute at a time.

Clients pay ~`rate` times a second through your `PaymentService.charge(key, account,
amount)`. Each payment has an idempotency key. A client waits up to 1 s for an answer;
if none comes it retries with the same key (up to 4 tries, backing off), and on a 409
(`Conflict`) it retries a little later.

Incidents come at random, like in production: the ledger gets slow (a retry arrives while
the first try is still charging), a load balancer drops answers on the way back (the
charge happened, the client never heard), or clients send the same payment twice at once.
The first incident is always a slow ledger at 0:20-0:30.

The run never restarts: the key store and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.idempotency.api import Conflict, KeyStore, Ledger, current_attempt

LAB = "idempotency"
NAMES = ("PaymentService",)
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a payment still running after this long is a bug
NET = 0.005  # one way, client <-> service
TIMEOUT = 1.0  # a client waits this long for an answer
MAX_TRIES = 4
BACKOFF = 0.2  # seconds before the first retry; doubles each time (with jitter)
CONFLICT_WAIT = 0.25  # after a 409
LEDGER_LATENCY = 0.02

# Attempt outcomes, from the client's side.
OK, LOST, LATE, CONFLICT = range(4)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "slow", 1.6, "ledger_lock")
KINDS = [
    Kind("slow", 0.4, median=9.0, shortest=5.0, longest=20.0, severity=(1.2, 2.5),
         causes=("ledger_lock", "disk_io", "vacuum", "failover")),
    Kind("resets", 0.35, median=9.0, shortest=5.0, longest=20.0, severity=(0.3, 0.7),
         causes=("lb_reset", "deploy_drain", "proxy_timeout")),
    Kind("storm", 0.25, median=8.0, shortest=4.0, longest=18.0, severity=(0.3, 0.6),
         causes=("sdk_bug", "double_click", "proxy_retry")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: 15 s of baseline before the next + time to judge


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 7 + 3)
        self.ledger = Ledger(LEDGER_LATENCY, random.Random(seed * 7 + 1), self.on_charge)
        self.store = KeyStore()
        self.service = code.PaymentService(self.ledger, self.store)
        self.lost_share = 0.0  # share of answers dropped on the way back
        self.double_share = 0.0  # share of payments sent twice at once
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.open: dict[int, dict] = {}  # running payments
        self.payments: list[tuple] = []  # (id, start, end, ok, attempts, charges, distinct answers)
        self.attempts: list[tuple] = []  # (start, payment, n, end, outcome, charged, after_first, dup)
        self.charged: dict[tuple[int, int], bool] = {}  # (payment, attempt) -> it was a second charge

    # ---- the ledger tells us about every charge

    def on_charge(self, who: tuple[int, int] | None, charge_id: int) -> None:
        if who is None or who[0] not in self.open:
            return
        p = self.open[who[0]]
        p["charges"] += 1
        self.charged[who] = p["charges"] > 1
        if p["first_done"] is None:
            p["first_done"] = now()

    # ---- clients

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for pid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.payment(pid, rng.randrange(1, 10_000), rng.randrange(100, 50_000)))

    async def payment(self, pid: int, account: int, amount: int) -> None:
        key = f"pay-{self.seed}-{pid}"
        p = {"start": now(), "tasks": 0, "charges": 0, "answers": set(), "first_done": None,
             "attempts": 0, "ok": False, "done": False, "end": 0.0}
        self.open[pid] = p
        if self.rng.random() < self.double_share:  # a buggy SDK or a double click: twice at once
            asyncio.ensure_future(self.attempt(pid, p, key, account, amount))
        for n in range(MAX_TRIES):
            outcome = await self.attempt(pid, p, key, account, amount)
            if outcome == OK:
                p["ok"] = True
                break
            if n < MAX_TRIES - 1:
                wait = CONFLICT_WAIT if outcome == CONFLICT else BACKOFF * 2 ** n * (0.5 + self.rng.random())
                await asyncio.sleep(wait)
        p["done"], p["end"] = True, now()
        self.maybe_finish(pid)

    async def attempt(self, pid: int, p: dict, key: str, account: int, amount: int) -> int:
        n = p["attempts"]
        p["attempts"] += 1
        p["tasks"] += 1
        answer = asyncio.get_running_loop().create_future()
        asyncio.ensure_future(self.serve(pid, p, n, key, account, amount, now(), answer))
        try:
            async with asyncio.timeout(TIMEOUT):
                return await asyncio.shield(answer)
        except TimeoutError:
            return LOST

    async def serve(self, pid: int, p: dict, n: int, key: str, account: int, amount: int,
                    start: float, answer: asyncio.Future) -> None:
        await asyncio.sleep(NET)
        after_first = p["first_done"] is not None
        token = current_attempt.set((pid, n))
        try:
            receipt = await self.service.charge(key, account, amount)
            outcome = OK
            if isinstance(receipt, dict) and "charge_id" in receipt:
                p["answers"].add(receipt["charge_id"])
        except Conflict:
            outcome = CONFLICT
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
            outcome = CONFLICT
        finally:
            current_attempt.reset(token)
        await asyncio.sleep(NET)
        if outcome == OK and self.rng.random() < self.lost_share:
            outcome = LOST  # the charge happened; the answer did not make it back
        elif now() - start > TIMEOUT:
            outcome = LATE  # the client stopped waiting
        if outcome in (OK, CONFLICT) and not answer.done():
            answer.set_result(outcome)
        dup = self.charged.pop((pid, n), None)
        self.attempts.append((start, pid, n, now(), outcome, dup is not None, after_first, bool(dup)))
        p["tasks"] -= 1
        self.maybe_finish(pid)

    def maybe_finish(self, pid: int) -> None:
        p = self.open.get(pid)
        if p is not None and p["done"] and p["tasks"] == 0:
            del self.open[pid]
            self.payments.append((pid, p["start"], p["end"], p["ok"], p["attempts"], p["charges"],
                                  len(p["answers"])))

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "slow":
                    self.ledger.latency = inc.severity
                case "resets":
                    self.lost_share = inc.severity
                case "storm":
                    self.double_share = inc.severity
            await asyncio.sleep(inc.t1 - now())
            self.ledger.latency, self.lost_share, self.double_share = LEDGER_LATENCY, 0.0, 0.0

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 40.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(p["start"] < b + DRAIN - STUCK for p in s.open.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, ok, attempts, charges, distinct answers)
                    "payments": s.take(s.payments, 1, a, b),
                    # (start, payment, attempt, end, outcome, charged, after_first, duplicate charge)
                    "attempts": s.take(s.attempts, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 40.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
