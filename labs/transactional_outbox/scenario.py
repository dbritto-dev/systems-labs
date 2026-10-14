"""Lab transactional_outbox: one endless run on virtual time, handed out a minute at a time.

Customers place ~`rate` orders a second through your `OrderService.place_order(order)`, in the
order service's pod. The same pod runs your `Relay`: the scenario calls `relay_once()` again and
again (at once after a busy round, every 0.1 s when idle, every 0.5 s while the broker is down).
Shipping is another service: it reads the topic in order and calls your
`ShippingConsumer.handle(event)` for each message, committing its offset every second.

Incidents come at random, like in production:
  crash      the order service's pod is killed again and again (an OOM kill, a deploy without a
             graceful shutdown, a lost node): every open transaction rolls back, the relay dies
             too, and the pod is back after 1 s. A kill strikes between two steps of the work:
             right after a publish was acknowledged, or right after a commit.
  broker     the broker is down (a lost leader, a rolling upgrade, an expired certificate): every
             publish raises BrokerUnavailable, and shipping cannot read either.
  locks      a share of the order database's commits fail (deadlocks, lock timeouts, a failover).
  relay      the relay alone is killed again and again (its own deploy, an OOM kill, a lost lease),
             right after a publish was acknowledged.
  rebalance  shipping's consumer group rebalances again and again: shipping goes back to its last
             committed offset (messages since then come again) on a fresh ShippingConsumer.
The first incident is always a crash loop at 0:20-0:30 (a kill every 2 s).

The run never restarts: the databases, the outbox and the topic carry on from minute to minute.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Iterator
from contextvars import ContextVar

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.vtime import VirtualRun, now
from labs.transactional_outbox.api import (
    Broker, BrokerUnavailable, CommitFailed, Database, DuplicateKey, Process, ProcessKilled, current_process,
)

LAB = "transactional_outbox"
NAMES = ("OrderService", "Relay", "ShippingConsumer")
PIECE = 60.0
DRAIN = 30.0  # simulate this far past a minute before handing it out (a broker outage + catching up)
STUCK = 20.0  # an order still running after this long is a bug
RESTART = 1.0  # a killed pod (or relay) is back after this long
RELAY_PAUSE = 0.1  # the relay's pause after a round with nothing to publish
RELAY_RETRY = 0.5  # ... and after BrokerUnavailable
TRIGGER_WAIT = 1.0  # a planned kill waits at most this long for its moment
CONSUMER_POLL = 0.02  # shipping looks for new messages this often when it has read everything
OFFSET_EVERY = 1.0  # shipping commits its offset this often
REBALANCE_PAUSE = 0.3  # shipping stops this long during a rebalance
SHIP = 0.001  # shipping's work per message (its database and the label printer)

# Who publishes.
SERVICE, RELAY = 0, 1
# What an order's request left behind when it ended.
SENT, QUEUED, DROPPED, PHANTOM, FAILED = range(5)
# What a message did at shipping.
SHIPPED, AGAIN, SKIPPED, GHOST = range(4)
# What was killed or restarted.
POD, RELAY_ONLY, REBALANCED = range(3)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "crash", 2.0, "oom_kill")
KINDS = [
    Kind("crash", 0.25, median=8.0, shortest=5.0, longest=15.0, severity=(1.5, 3.0),
         causes=("oom_kill", "deploy_kill", "node_lost", "spot_reclaim")),
    Kind("broker", 0.25, median=10.0, shortest=5.0, longest=20.0, severity=(1.0, 1.0),
         causes=("leader_lost", "rolling_upgrade", "cert_expired", "disk_full")),
    Kind("locks", 0.15, median=8.0, shortest=4.0, longest=15.0, severity=(0.2, 0.5),
         causes=("migration_lock", "batch_deadlock", "db_failover", "hot_row")),
    Kind("relay", 0.15, median=8.0, shortest=4.0, longest=15.0, severity=(1.5, 3.0),
         causes=("relay_oom", "relay_deploy", "lease_lost")),
    Kind("rebalance", 0.2, median=8.0, shortest=4.0, longest=15.0, severity=(1.5, 3.0),
         causes=("consumer_deploy", "autoscale", "missed_heartbeat")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # calm after an incident: the lag check after it, then 15 s of baseline before the next

who_publishes: ContextVar[int] = ContextVar("who_publishes", default=SERVICE)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code = code
        self.seed = seed
        self.rate = rate
        self.rng = random.Random(seed * 13 + 5)
        self.db = Database(on_commit=self.on_commit, on_fetch=self.on_fetch)
        self.broker = Broker(on_publish=self.on_publish)
        self.ship_db = Database(latency=0.0, commit_latency=0.0, on_commit=self.on_ship_commit)  # time is in SHIP
        self.pod = Process()  # the order service and its relay
        self.relay_proc = Process()  # the relay alone (a relay incident kills only this)
        self.service = code.OrderService(self.db, self.broker)
        self.pod_tasks: set[asyncio.Task] = set()
        self.relay_task: asyncio.Task | None = None
        self.pod_up = True
        self.back_at = 0.0  # when the pod (or relay) was last back after a kill
        self.trigger: tuple[str, str, asyncio.Future] | None = None  # (step, target, done)
        self.rebalance = False
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.records: dict[str, dict] = {}  # order id -> what happened to it
        self.open: dict[int, dict] = {}  # orders whose request is still running
        self.done: list[dict] = []
        self.publishes: list[tuple] = []  # (t, order, who, ok, repeat)
        self.deliveries: list[tuple] = []  # (t, order id, kind) - the kind is final when handed out
        self.polls: list[tuple] = []  # (t, rows fetched)
        self.backlog: list[tuple] = []  # (t, unsent outbox rows)
        self.kills: list[tuple] = []  # (t, back at, what)
        self._effects: list[str] = []

    # ---- what the databases and the broker tell us

    def on_commit(self, writes: dict[str, list[dict]]) -> None:
        for row in writes.get("orders", []):
            rec = self.records.get(row.get("id"))
            if rec is not None and rec["commit"] is None:
                rec["commit"] = now()
        for row in writes.get("outbox", []):
            rec = self.records.get(row.get("order_id")) if isinstance(row, dict) else None
            if rec is not None:
                rec["queued"] = True
        if writes.get("orders") or writes.get("outbox"):
            self.maybe_kill("commit")

    def on_fetch(self, n: int) -> None:
        self.polls.append((now(), n))

    def on_publish(self, event: dict, ok: bool) -> None:
        rec = self.records.get(event.get("order_id")) if isinstance(event, dict) else None
        n = rec["n"] if rec is not None else -1
        repeat = rec is not None and rec["publishes"] > 0
        who = who_publishes.get()
        self.publishes.append((now(), n, who, ok, repeat))
        if ok:
            if rec is not None:
                rec["publishes"] += 1
            self.maybe_kill("publish", who)

    def on_ship_commit(self, writes: dict[str, list[dict]]) -> None:
        self._effects += [row.get("order_id") for row in writes.get("shipments", [])]

    # ---- kills

    def maybe_kill(self, step: str, who: int | None = None) -> None:
        """A planned kill strikes at its moment: right after a commit or an acknowledged publish."""
        if self.trigger is None:
            return
        want, target, done = self.trigger
        proc = current_process.get()
        if want != step or done.done():
            return
        if target == "pod" and proc is not self.pod and proc is not self.relay_proc:
            return
        if target == "relay" and (proc is not self.relay_proc or who != RELAY):
            return
        done.set_result(True)
        self.kill(target)  # now: the code that just published or committed runs no further step

    async def strike(self, step: str, target: str) -> None:
        done = asyncio.get_running_loop().create_future()
        self.trigger = (step, target, done)
        try:
            async with asyncio.timeout(TRIGGER_WAIT):
                await done
        except TimeoutError:
            self.kill(target)  # nothing came: kill it anyway
        self.trigger = None

    def kill(self, target: str) -> None:
        self.relay_proc.dead = True
        if self.relay_task is not None:
            self.relay_task.cancel()
        if target == "pod":
            self.pod.dead = True
            self.pod_up = False
            for task in list(self.pod_tasks):
                task.cancel()
        self.back_at = now() + RESTART
        self.kills.append((now(), self.back_at, POD if target == "pod" else RELAY_ONLY))
        asyncio.ensure_future(self.restart(target))

    async def restart(self, target: str) -> None:
        await asyncio.sleep(RESTART)
        if target == "pod":
            self.pod = Process()
            self.service = self.code.OrderService(self.db, self.broker)
            self.pod_up = True
        if self.pod_up and (self.relay_task is None or self.relay_task.done()):  # one relay at a time
            self.start_relay()

    # ---- the order service

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 13)
        for n, t in enumerate(arrivals(self.rate, self.seed, 0.0, rng)):
            await asyncio.sleep(t - now())
            order = {"id": f"ord-{self.seed}-{n}", "customer": rng.randrange(1, 100_000),
                     "total": rng.randrange(500, 50_000)}
            rec = {"n": n, "start": now(), "end": None, "commit": None, "queued": False, "publishes": 0,
                   "first": None, "effects": 0, "outcome": FAILED}
            self.records[order["id"]] = rec
            self.open[n] = rec
            if not self.pod_up:  # the pod is restarting: connection refused
                self.finish(rec)
                continue
            task = asyncio.ensure_future(self.serve(order, rec))
            self.pod_tasks.add(task)
            task.add_done_callback(self.pod_tasks.discard)

    async def serve(self, order: dict, rec: dict) -> None:
        current_process.set(self.pod)
        who_publishes.set(SERVICE)
        try:
            await self.service.place_order(order)
        except (CommitFailed, BrokerUnavailable, DuplicateKey, ProcessKilled, asyncio.CancelledError):
            pass  # the customer sees an error (or nothing: the process died)
        except Exception as exc:  # a bug in the code under test: surface it
            self.bugs.append(exc)
        finally:
            self.finish(rec)

    def finish(self, rec: dict) -> None:
        rec["end"] = now()
        saved, published, queued = rec["commit"] is not None, rec["publishes"] > 0, rec["queued"]
        if saved:
            rec["outcome"] = SENT if published else QUEUED if queued else DROPPED
        else:
            rec["outcome"] = PHANTOM if published else FAILED
        self.open.pop(rec["n"], None)
        self.done.append(rec)

    # ---- the relay (in the pod)

    def start_relay(self) -> None:
        self.relay_proc = Process()
        self.relay_task = asyncio.ensure_future(self.relay_loop(self.relay_proc))

    async def relay_loop(self, proc: Process) -> None:
        current_process.set(proc)
        who_publishes.set(RELAY)
        relay = self.code.Relay(self.db, self.broker)
        while not proc.dead:
            try:
                n = await relay.relay_once()
            except NotImplementedError:
                return  # stage 0: there is no relay yet
            except BrokerUnavailable:
                await asyncio.sleep(RELAY_RETRY)
                continue
            except (ProcessKilled, asyncio.CancelledError):
                return
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return
            try:
                await asyncio.sleep(0.001 if n else RELAY_PAUSE)
            except asyncio.CancelledError:
                return

    # ---- shipping

    async def consume(self) -> None:
        current_process.set(Process())  # shipping is never killed here; it rebalances
        consumer = self.code.ShippingConsumer(self.ship_db)
        offset = committed = 0
        last_commit = now()
        while True:
            if self.rebalance:
                self.rebalance = False
                offset = committed  # back to the last committed offset: these come again
                consumer = self.code.ShippingConsumer(self.ship_db)
                await asyncio.sleep(REBALANCE_PAUSE)
                continue
            if self.broker.down or offset >= self.broker.end:
                await asyncio.sleep(CONSUMER_POLL)
            else:
                event = self.broker.read(offset)
                self._effects = []
                try:
                    await consumer.handle(event)
                except Exception as exc:  # a bug in the code under test: surface it
                    self.bugs.append(exc)
                offset += 1
                self.delivered(event)
                await asyncio.sleep(SHIP)
            if now() - last_commit >= OFFSET_EVERY:
                committed, last_commit = offset, now()
                self.broker.trim(committed)

    def delivered(self, event: dict) -> None:
        oid = event.get("order_id") if isinstance(event, dict) else None
        rec = self.records.get(oid)
        if rec is not None and rec["first"] is None:
            rec["first"] = now()
        if not self._effects:
            self.deliveries.append((now(), oid, SKIPPED))
        for shipped in self._effects:
            r = self.records.get(shipped)
            if r is not None:
                r["effects"] += 1
            self.deliveries.append((now(), shipped, SHIPPED if r is None or r["effects"] == 1 else AGAIN))

    # ---- incidents and gauges

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            match inc.kind:
                case "crash" | "relay":
                    target = "pod" if inc.kind == "crash" else "relay"
                    k = 0
                    while now() < inc.t1:
                        # Alternate the moment: after an acknowledged publish, then after a commit.
                        await self.strike("publish" if k % 2 == 0 or target == "relay" else "commit", target)
                        k += 1
                        nxt = max(inc.t0 + k * inc.severity, self.back_at + 0.3)
                        if nxt >= inc.t1:
                            break
                        await asyncio.sleep(nxt - now())
                case "broker":
                    self.broker.down = True
                case "locks":
                    share, rng = inc.severity, self.rng
                    self.db.fail_commit = lambda: rng.random() < share
                case "rebalance":
                    k = 0
                    while now() < inc.t1:
                        self.rebalance = True
                        self.kills.append((now(), now() + REBALANCE_PAUSE, REBALANCED))
                        k += 1
                        await asyncio.sleep(max(0.0, inc.t0 + k * inc.severity - now()))
            await asyncio.sleep(max(0.0, inc.t1 - now()))
            self.broker.down = False
            self.db.fail_commit = lambda: False

    async def gauges(self) -> None:
        while True:
            self.backlog.append((now(), self.db.unsent))
            await asyncio.sleep(0.25)

    # ---- handing out a minute

    def orders(self, a: float, b: float) -> list[tuple]:
        out = sorted((r for r in self.done if r["start"] < b), key=lambda r: r["start"])
        self.done = [r for r in self.done if r["start"] >= b]
        return [(r["n"], r["start"], r["end"], r["outcome"], r["commit"], r["first"], r["effects"], r["publishes"])
                for r in out if r["start"] >= a]

    def shipping(self, a: float, b: float) -> list[tuple]:
        rows = self.take(self.deliveries, 0, a, b)
        out = []
        for t, oid, kind in rows:
            rec = self.records.get(oid)
            if kind != SKIPPED and rec is not None and rec["commit"] is None:
                kind = GHOST  # a shipment for an order that was never saved
            out.append((t, rec["n"] if rec is not None else -1, kind))
        return out

    def forget(self, before: float) -> None:
        for oid in [k for k, r in self.records.items() if r["end"] is not None and r["start"] < before]:
            del self.records[oid]

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 50.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(s.traffic())
    sim.spawn(s.consume())
    sim.spawn(s.chaos())
    sim.spawn(s.gauges())
    sim.spawn(_start(s))
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            if any(r["start"] < b + DRAIN - STUCK for r in s.open.values()):
                raise RuntimeError(lab_text(LAB).STRINGS["stuck"].format(seconds=STUCK))
            piece = {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    # (id, start, end, outcome, committed at, first at shipping, shipments, publishes)
                    "orders": s.orders(a, b),
                    # (t, order, who, ok, repeat)
                    "publishes": s.take(s.publishes, 0, a, b),
                    # (t, order, kind)
                    "deliveries": s.shipping(a, b),
                    # (t, rows fetched)
                    "polls": s.take(s.polls, 0, a, b),
                    # (t, unsent outbox rows)
                    "backlog": s.take(s.backlog, 0, a, b),
                    # (t, back at, what)
                    "kills": s.take(s.kills, 0, a, b),
                },
            }
            s.forget(a - PIECE)
            yield piece
    finally:
        sim.close()


async def _start(s: _Sim) -> None:
    s.start_relay()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 50.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
