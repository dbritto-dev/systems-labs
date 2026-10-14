"""Lab saga_orchestration: one endless run on virtual time, handed out a minute at a time.

Customers place ~`rate` orders a second. Each order is a saga run by your
`Orchestrator.place(saga_id, order)`: charge the card (payments), reserve the items (stock),
book a courier (shipping). About 2% of cards are declined, always.

Incidents come at random, like in production: a flash sale sells items out (the reservation
says no after the card was charged), the carrier is down (the booking says no after both),
a service times out (the step may or may not have happened), or the orchestrator itself dies
(a deploy, an OOM kill): every saga it was running stops where it was. A new orchestrator
starts ~2-5 s later with the same services and the same log, and `recover()` is called once.
Orders that arrive while it is down wait at the door. The first incident is always a slow
carrier at 0:20-0:30 whose waiting sagas get the orchestrator OOM-killed at 0:26.

The run never restarts: the services, the log and the clock carry on from minute to minute.
"""

from __future__ import annotations

import asyncio
import contextvars
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.saga_orchestration import lab
from labs.saga_orchestration.api import (
    DECLINED, OK, Crashed, Order, Plant, SagaLog, StepFailed, current_order, epoch, services,
)

LAB = "saga_orchestration"
NAMES = ("Orchestrator",)
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
STUCK = 30.0  # a saga still running after this long is a bug
CARD_DECLINED = 0.02  # share of cards that are declined, any day

# Saga outcomes, once everything has settled.
ORPHAN, ROLLED_BACK, DONE = range(3)

# Causes are keys; their words are in text/<lang>.py (CAUSES). A timeout's cause names the service.
TIMEOUT_CAUSES = {"psp_overload": 0, "psp_network": 0, "inventory_gc": 1, "inventory_lock": 1,
                  "carrier_slow": 2, "carrier_lb": 2}
FIRST = Planned(20.0, 30.0, "oom", 0.5, "carrier_slow_oom")
KINDS = [
    Kind("timeouts", 0.35, median=9.0, shortest=5.0, longest=20.0, severity=(0.2, 0.5),
         causes=tuple(TIMEOUT_CAUSES)),
    Kind("stockout", 0.2, median=9.0, shortest=5.0, longest=20.0, severity=(0.2, 0.6),
         causes=("flash_sale", "inventory_sync", "warehouse_count")),
    Kind("shipping", 0.2, median=8.0, shortest=4.0, longest=18.0, severity=(0.5, 1.0),
         causes=("carrier_outage", "carrier_cert", "carrier_ratelimit")),
    Kind("crash", 0.25, median=3.0, shortest=1.5, longest=5.0, severity=(1.0, 1.0),
         causes=("deploy", "oom_kill", "node_evicted")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: 15 s of baseline before the next + time to judge


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def unlucky(seed: int, order: int, salt: int) -> float:
    """A fixed draw per order: the same card is declined however often you try it."""
    return random.Random(seed * 1_000_003 + order * 7 + salt).random()


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code = code
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 11 + 5)
        self.plant = Plant()
        self.payments, self.stock, self.shipping = services(seed, self.plant, self.on_call)
        self.svcs = (self.payments, self.stock, self.shipping)
        self.log = SagaLog(plant=self.plant)
        self.stockout = 0.0  # share of orders out of stock
        self.carrier_down = 0.0  # share of bookings the carrier refuses
        self.payments.refuse = lambda o: unlucky(seed, o.id, 1) < CARD_DECLINED
        self.stock.refuse = lambda o: self.stockout > 0 and unlucky(seed, o.id, 2) < self.stockout
        self.shipping.refuse = lambda o: self.carrier_down > 0 and self.rng.random() < self.carrier_down
        self.up = True
        self.orch = None
        self.recovering: asyncio.Task | None = None
        self.running: dict[int, asyncio.Task] = {}  # place() tasks of the live orchestrator
        self.queued: list[Order] = []  # orders waiting at the door while it is down
        self.sagas: dict[int, dict] = {}  # orders not handed out yet
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.orders: list[tuple] = []
        self.calls: list[tuple] = []  # (start, order, service, undo, end, outcome)

    # ---- every call to a service ends here

    def on_call(self, start: float, order: int, service: int, undo: bool, end: float, outcome: int) -> None:
        self.calls.append((start, order, service, undo, end, outcome))
        s = self.sagas.get(order)
        if s is None:
            return
        s["last"] = max(s["last"], end)
        if not undo and outcome == DECLINED:
            s["declined"] = True  # somebody said no: this order could not complete

    # ---- the orchestrator's life

    def _spawn(self, coro, order: int | None = None) -> asyncio.Task:
        """A task of the live orchestrator: its calls die with it."""
        ctx = contextvars.copy_context()
        ctx.run(epoch.set, self.plant.epoch)
        ctx.run(current_order.set, order)
        return asyncio.get_running_loop().create_task(coro, context=ctx)

    def boot(self) -> None:
        self.orch = self.code.Orchestrator(self.payments, self.stock, self.shipping, self.log)

    def crash(self) -> None:
        self.plant.epoch += 1  # every call from the old one now raises Crashed
        self.up = False
        for oid, task in self.running.items():
            self.sagas[oid]["crashed"] = True
            task.cancel()
        self.running.clear()
        if self.recovering is not None:
            self.recovering.cancel()
            self.recovering = None
        self.orch = None  # everything it had in memory is gone

    def restart(self) -> None:
        self.plant.epoch += 1
        self.boot()
        self.recovering = self._spawn(self.recover())  # first, so it sees the log before new sagas
        self.up = True
        queued, self.queued = self.queued, []
        for order in queued:
            self.start(order)

    async def recover(self) -> None:
        try:
            await self.orch.recover()
        except (Crashed, asyncio.CancelledError, StepFailed):
            pass
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)

    # ---- customers

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7)
        for oid, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            order = Order(oid, rng.randrange(1, 10_000), rng.randrange(500, 30_000), rng.randrange(1, 4),
                          f"{rng.randrange(1, 999)} Main St")
            self.sagas[oid] = {"start": now(), "last": now(), "returned": None, "failed": False,
                               "declined": False, "crashed": False}
            if self.up:
                self.start(order)
            else:
                self.queued.append(order)

    def start(self, order: Order) -> None:
        self.running[order.id] = self._spawn(self.place(order), order.id)

    async def place(self, order: Order) -> None:
        orch = self.orch
        gave_up = True
        try:
            gave_up = await orch.place(f"order-{order.id}", order) is not True
        except (Crashed, asyncio.CancelledError):
            return  # it died with the orchestrator
        except StepFailed:
            pass  # gave up: whatever was done stays done
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
        s = self.sagas.get(order.id)
        if s is not None:
            s["returned"], s["failed"] = now(), gave_up
        if self.running.get(order.id) is asyncio.current_task():
            del self.running[order.id]

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "timeouts":
                    self.svcs[TIMEOUT_CAUSES[inc.cause]].timeout_share = inc.severity
                case "oom":
                    self.shipping.timeout_share = inc.severity
                case "stockout":
                    self.stockout = inc.severity
                case "shipping":
                    self.carrier_down = inc.severity
            down = lab.downtime(inc.kind, inc.t0, inc.t1)
            if down is not None:
                await asyncio.sleep(down[0] - now())
                self.crash()
                await asyncio.sleep(down[1] - now())
                self.restart()
            await asyncio.sleep(inc.t1 - now())
            for svc in self.svcs:
                svc.timeout_share = 0.0
            self.stockout = self.carrier_down = 0.0

    # ---- handing out a minute

    def settle(self, a: float, b: float) -> list[tuple]:
        """Judge every order that started before b by what the services hold now, and forget it."""
        out = []
        for oid in [o for o, s in self.sagas.items() if s["start"] < b]:
            s = self.sagas.pop(oid)
            held = [svc.held(oid) for svc in self.svcs]
            status = DONE if held == [1, 1, 1] else ROLLED_BACK if held == [0, 0, 0] else ORPHAN
            known = any(svc.known_held(oid) for svc in self.svcs)
            mask = sum(1 << i for i, h in enumerate(held) if h)
            end = max(s["start"], s["last"], s["returned"] or 0.0)
            out.append((oid, s["start"], end, status, status == DONE, self.payments.made(oid), s["failed"],
                        known, s["crashed"], s["declined"], mask))
            for svc in self.svcs:
                svc.forget(oid)
        return sorted((r for r in out if r[1] >= a), key=lambda r: r[1])

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 20.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    s.boot()
    sim.spawn(s.traffic())
    sim.spawn(s.chaos())
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            limit = b + DRAIN - STUCK
            if any(s.sagas[o]["start"] < limit for o in s.running if o in s.sagas):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned
                              if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, status, done, charges, gave up, still holds what it was told, crashed,
                    #  declined, held mask)
                    "orders": s.settle(a, b),
                    # (start, order, service, undo, end, outcome)
                    "calls": s.take(s.calls, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 20.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
