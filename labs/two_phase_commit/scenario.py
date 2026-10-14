"""Lab two_phase_commit: one endless run on virtual time, handed out a minute at a time.

A bank's accounts live on 3 shards (n1, n2, n3); the coordinator is n0. Clients send ~`rate`
transfers a second to the coordinator. Every transfer touches the three shards: it takes money from a
customer on one, pays a merchant on another and the bank's fee on the third (the three add up to 0).
Merchants and fee buckets are few, so their rows are hot: a row held locked blocks the next transfers.

Incidents come at random, like in production: a shard votes no for a share of transfers (lock
timeouts behind a long report, a new constraint, frozen accounts), a shard crashes right after voting
yes (it comes back with its disk: prepare records and locks), the coordinator crashes (a deploy, an
eviction: at once; an OOM kill: while it sends a commit, so one shard gets it and the others do not),
or the network cuts a shard off from the coordinator. The first incident is always n2 busy with lock
timeouts at 0:20-0:30; at 0:26 the coordinator, full of waiting transfers, is OOM-killed while it
sends a commit, and it is back at 0:29.

The checker reads the shards' disks (balances, prepare records, locks), outside the network.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Message, Network, RPCError
from core.vtime import VirtualRun, now
from labs.two_phase_commit import lab
from labs.two_phase_commit.api import (
    APPLIED, LOCK_TIMEOUT, PREPARED, REFUSED, RELEASED, Crashed, DecisionLog, Life, ShardDB,
)

LAB = "two_phase_commit"
NAMES = ("Coordinator", "Shard")
PIECE = 60.0
DRAIN = 20.0  # simulate this far past a minute before handing it out
LATENCY = 0.03  # seconds per message between the coordinator and a shard
CLIENT_TIMEOUT = 2.0
CHECK_EVERY = 0.25  # how often the checker reads the shards' disks
DOUBT_AGE = 0.5  # a transfer prepared this long without a decision is "in doubt" on screen
GRACE = 0.5  # a commit whose writes land this close together moves no money in between
ARMED = 1.0  # a crash waiting for its moment (a commit sent, a yes vote) happens anyway after this long
COORD = "n0"
SHARD_IDS = ("n1", "n2", "n3")
CUSTOMERS, MERCHANTS, FEES = 300, 4, 3
START_BALANCE = 1_000_000

# Transfer outcomes, once everything has settled.
COMMITTED, ABORTED, PARTIAL, IN_DOUBT = range(4)
# Message kinds, for the pictures.
(M_TRANSFER, M_WRITE, M_PREPARE, M_YES, M_NO, M_COMMIT, M_ABORT, M_ACK, M_ASK, M_ANSWER,
 M_OTHER) = range(11)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "overload", 0.5, "report_oom")
KINDS = [
    Kind("refuse", 0.3, median=8.0, shortest=4.0, longest=18.0, severity=(0.2, 0.6),
         causes=("report_locks", "check_constraint", "frozen_accounts")),
    Kind("shard_crash", 0.25, median=5.0, shortest=3.0, longest=10.0,
         causes=("shard_oom", "kernel_panic", "host_reboot")),
    Kind("coord_crash", 0.25, median=4.0, shortest=2.0, longest=7.0,
         causes=("coord_oom", "deploy", "node_evicted")),
    Kind("partition", 0.2, median=6.0, shortest=3.0, longest=12.0,
         causes=("switch_port", "firewall_rule", "bgp_flap")),
]
MEAN_GAP = 30.0
QUIET = 25.0  # calm after an incident: time to judge it, and 15 s of baseline before the next
WAITING = {"report_locks", "report_oom"}  # refusals that are lock timeouts (they wait first)
MID_DECISION = {"coord_oom", "report_oom"}  # the coordinator dies while it sends a commit


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, seed: int) -> int:
    """Which shard the incident hits (1..3; the first one always hits n2)."""
    if inc.t0 == FIRST.t0:
        return 2
    return random.Random(f"{seed}:{inc.t0}:victim").randrange(1, 4)


def kind_of(body: dict) -> int:
    t = body.get("type", "")
    return {"transfer": M_TRANSFER, "write": M_WRITE, "prepare": M_PREPARE, "commit": M_COMMIT,
            "abort": M_ABORT, "status": M_ASK, "status_ok": M_ANSWER, "commit_ok": M_ACK,
            "abort_ok": M_ACK, "write_ok": M_ACK}.get(t, M_OTHER)


class _Net(Network):
    """The network, plus dead nodes: what arrives at a dead node is lost."""

    def send(self, src: str, dest: str, body) -> None:
        super().send(src, dest, body)
        rec = self.log[-1]
        kind = kind_of(body)
        if body.get("type") == "prepare_ok" or (kind == M_OTHER and "vote" in body):
            kind = M_YES if body.get("vote") is True else M_NO
        rec.type = kind  # type: ignore[assignment]  # the picture wants the kind, not the word

    def _arrive(self, msg: Message, rec) -> None:
        if getattr(self.nodes.get(msg.dest), "dead", False):
            rec.dropped = True
            return
        super()._arrive(msg, rec)


def _managed(cls, sim: "_Sim"):
    """Your node, plus what the scenario needs to crash and restart it."""

    class Managed(cls):
        def __init__(self, *args) -> None:
            self._tasks: list = []
            self.dead = False
            self.die_on = None  # dies right after sending a message this says yes to
            super().__init__(*args)

        def _track(self, task, coro=None):
            self._tasks.append((task, coro))
            if len(self._tasks) > 512:
                self._tasks = [(t, c) for t, c in self._tasks if not t.done()]
            return task

        async def _run(self, coro) -> None:
            try:
                await coro
            except (Crashed, TimeoutError, RPCError):
                pass  # it died, or an RPC inside a handler went unanswered: the handler's business
            except Exception as exc:  # noqa: BLE001 - a bug in the code under test: surface it
                self.net.bugs.append(exc)

        def spawn(self, coro):
            if self.dead:
                coro.close()
                return None
            return self._track(asyncio.ensure_future(self._run(coro)), coro)

        def every(self, seconds, fn):
            async def loop() -> None:
                while True:
                    await asyncio.sleep(seconds)
                    await self._run(fn())

            return self._track(asyncio.ensure_future(loop()))

        def send(self, dest, body):
            if self.dead:
                return
            super().send(dest, body)
            if self.die_on is not None and self.die_on(body):
                self.die_on = None
                sim.kill(self.node_id, self)

        def _deliver(self, msg):
            if self.dead:
                return
            reply_to = msg.body.get("in_reply_to")
            if reply_to is not None:
                fut = self._waiting.get(reply_to)
                if fut is not None and not fut.done():
                    fut.set_result(msg.body)
                return
            handler = getattr(self, f"on_{msg.body.get('type', '')}", None)
            if handler is None:
                if "msg_id" in msg.body:
                    self.reply(msg, {"type": "error", "code": 10, "text": f"no handler for {msg.body.get('type')!r}"})
                return
            coro = handler(msg)
            self._track(asyncio.ensure_future(self._run(coro)), coro)

        def kill(self) -> None:
            self.dead = True
            for task, coro in self._tasks:
                task.cancel()
                if coro is not None and inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
                    coro.close()  # it never started: nothing to clean up
            self._tasks = []

    Managed.__name__ = cls.__name__
    return Managed


def _commit_or_write(body) -> bool:
    return body.get("type") in ("commit", "write")


def _yes(body) -> bool:
    return body.get("type") == "prepare_ok" and body.get("vote") is True


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = _Net(latency=LATENCY, jitter=0.2, seed=seed)
        self.ids = [COORD, *SHARD_IDS]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.classes = {COORD: _managed(code.Coordinator, self)}
        shard_cls = _managed(code.Shard, self)
        self.classes.update({n: shard_cls for n in SHARD_IDS})
        balances = {f"c{i}": START_BALANCE for i in range(CUSTOMERS)}
        balances |= {f"m{i}": 0 for i in range(MERCHANTS)} | {f"f{i}": 0 for i in range(FEES)}
        self.dbs = [ShardDB(i, balances, self.on_event) for i in range(lab.SHARDS)]
        self.log = DecisionLog()
        self.nodes: dict[str, object] = {}
        self.client = Client("c1")
        self.net.join(self.client)
        self.rng = random.Random(seed * 13 + 1)
        self.planned: list[Planned] = []
        self.victims: dict[float, int] = {}
        self.cut = 0  # shards cut off from the coordinator (bits 1..3)
        self.txns: dict[int, dict] = {}  # transfers not handed out yet
        self.money: dict[int, list] = {}  # txn -> [writes applied, money they moved, first applied at]
        self.drift = 0  # money moved by transfers applied on some shards but not all
        self.young: deque[tuple[float, int]] = deque()  # (first applied at, txn) of the last GRACE seconds
        self.state: list[tuple] = []
        self._ids = itertools.count()

    # ---- the nodes' lives

    def boot(self, node_id: str) -> None:
        life = Life()
        if node_id == COORD:
            node = self.classes[node_id](node_id, self.ids, self.log.view(life))
        else:
            node = self.classes[node_id](node_id, self.ids, self.dbs[self.index[node_id] - 1].view(life))
        node.life = life
        self.nodes[node_id] = node
        self.net.join(node)
        node.spawn(node.recover())

    def kill(self, node_id: str, node=None) -> None:
        """Crash a node (this run of it: `node`, else the one running now)."""
        node = node or self.nodes[node_id]
        if node.dead:
            return
        node.life.dead = True
        node.kill()

    async def setup(self) -> None:
        for n in self.ids:
            self.boot(n)

    async def arm(self, node_id: str, when) -> None:
        """Crash the node right after it sends a message `when` says yes to (or after ARMED s)."""
        node = self.nodes[node_id]
        node.die_on = when
        await asyncio.sleep(ARMED)
        node.die_on = None
        self.kill(node_id, node)

    # ---- what the shards' disks tell us

    def on_event(self, kind: int, shard: int, txn: str, t: float, value: int) -> None:
        try:
            tid = int(txn[1:])
        except (TypeError, ValueError):
            return
        x = self.txns.get(tid)
        if kind == APPLIED:
            self.apply_money(tid, value, t)
        if x is None:
            return
        if kind == PREPARED and x["prep"][shard] < 0:
            x["prep"][shard] = t
        elif kind == APPLIED:
            x["applied"][shard] = t
        elif kind == RELEASED:
            x["released"][shard] = t
        elif kind == REFUSED:
            x["refused"] = True

    def apply_money(self, tid: int, delta: int, t: float) -> None:
        m = self.money.get(tid)
        if m is None:
            m = self.money[tid] = [0, 0, t]
            self.young.append((t, tid))
        if 0 < m[0] < lab.SHARDS:
            self.drift -= m[1]
        m[0] += 1
        m[1] += delta
        if m[0] < lab.SHARDS:
            self.drift += m[1]
        else:
            del self.money[tid]

    def money_now(self, t: float) -> int:
        """Money created (+) or destroyed (-) by transfers applied on some shards but not all,
        leaving out commits still landing (their writes arrive a few ms apart)."""
        while self.young and self.young[0][0] < t - GRACE:
            self.young.popleft()
        landing = sum(self.money[tid][1] for _, tid in self.young if tid in self.money)
        return self.drift - landing

    # ---- clients

    async def transfer(self, tid: int, writes: dict) -> None:
        ok = False
        try:
            reply = await self.client.rpc(COORD, {"type": "transfer", "txn": f"t{tid}", "writes": writes},
                                          timeout=CLIENT_TIMEOUT)
            ok = reply.get("committed") is True
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the client gives up
            ok = False
        x = self.txns.get(tid)
        if x is not None:
            x["end"], x["ok"] = now(), ok

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 7 + 2)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            tid = next(self._ids)
            p, q, r = rng.sample(range(lab.SHARDS), 3)
            amount = rng.randrange(10, 500)
            fee = max(1, amount // 50)
            deltas = [0] * lab.SHARDS
            deltas[p], deltas[q], deltas[r] = -amount, amount - fee, fee
            writes = {SHARD_IDS[p]: [f"c{rng.randrange(CUSTOMERS)}", -amount],
                      SHARD_IDS[q]: [f"m{rng.randrange(MERCHANTS)}", amount - fee],
                      SHARD_IDS[r]: [f"f{rng.randrange(FEES)}", fee]}
            self.txns[tid] = {"start": now(), "end": None, "ok": False, "refused": False, "deltas": tuple(deltas),
                              "prep": [-1.0] * 3, "applied": [-1.0] * 3, "released": [-1.0] * 3}
            asyncio.ensure_future(self.transfer(tid, writes))

    # ---- incidents

    def refuse(self, shard: int, share: float, cause: str) -> None:
        wait = LOCK_TIMEOUT if cause in WAITING else 0.0
        rng = random.Random(f"{self.seed}:{shard}:{share}")
        self.dbs[shard - 1].refuse = lambda txn: wait if rng.random() < share else None

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            v = victim(inc, self.seed)
            self.victims[inc.t0] = v
            await asyncio.sleep(inc.t0 - now())
            shard = SHARD_IDS[v - 1]
            if inc.kind in ("overload", "refuse"):
                self.refuse(v, inc.severity, inc.cause)
            if inc.kind in ("overload", "coord_crash"):
                down = lab.downtime(inc.kind, inc.t0, inc.t1)
                await asyncio.sleep(down[0] - now())
                if inc.cause in MID_DECISION:
                    asyncio.ensure_future(self.arm(COORD, _commit_or_write))
                else:
                    self.kill(COORD)
                await asyncio.sleep(down[1] - now())
                self.kill(COORD)  # if it was still waiting for its moment
                self.boot(COORD)
            elif inc.kind == "shard_crash":
                asyncio.ensure_future(self.arm(shard, _yes))  # it dies right after voting yes
                await asyncio.sleep(inc.t1 - now())
                self.kill(shard)
                self.boot(shard)
            elif inc.kind == "partition":
                self.cut = 1 << v
                self.net.partition([{COORD, *(s for s in SHARD_IDS if s != shard)}, {shard}])
            await asyncio.sleep(inc.t1 - now())
            self.net.heal()
            self.cut = 0
            for db in self.dbs:
                db.refuse = lambda txn: None

    # ---- the checker (outside the network)

    async def checker(self) -> None:
        while True:
            await asyncio.sleep(CHECK_EVERY)
            t = now()
            held = tuple(len(db.prepared) for db in self.dbs)
            doubt = tuple(sum(1 for _, _, since in db.prepared.values() if t - since >= DOUBT_AGE)
                          for db in self.dbs)
            down = sum(1 << i for i, n in enumerate(self.ids) if self.nodes[n].dead)
            self.state.append((t, held, doubt, down, self.cut, self.money_now(t)))

    # ---- handing out a minute

    def settle(self, a: float, b: float) -> list[tuple]:
        """Judge every transfer that started before b by what the shards' disks hold now, and forget it."""
        out = []
        for tid in [k for k, x in self.txns.items() if x["start"] < b]:
            x = self.txns.pop(tid)
            applied = [at >= 0 for at in x["applied"]]
            pending = [f"t{tid}" in db.prepared for db in self.dbs]
            if all(applied):
                status = COMMITTED
            elif not any(applied) and not any(pending):
                status = ABORTED
            elif any(applied) and any(not ap and not pe for ap, pe in zip(applied, pending)):
                status = PARTIAL
            else:
                status = IN_DOUBT
            if any(pending):
                resolved = None  # still prepared somewhere: in doubt, its row still locked
            elif any(p >= 0 for p in x["prep"]):
                resolved = max(x["released"])
            else:
                resolved = -1.0  # never prepared anywhere
            end = max(x["start"], x["end"] or 0.0, resolved or 0.0, *x["applied"])
            out.append((tid, x["start"], end, status, x["ok"], x["refused"], x["deltas"], tuple(x["applied"]),
                        resolved, tuple(x["prep"]), x["end"] or x["start"]))
        return sorted((r for r in out if r[1] >= a), key=lambda r: r[1])

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages sent in [a, b): (sent, src, dest, arrived or None, kind); -1 is the clients."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.sent < a or d.dest not in self.index:
                continue  # replies to the clients are not drawn
            out.append((d.sent, self.index.get(d.src, -1), self.index[d.dest], d.arrived, d.type))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 10.0) -> Iterator[dict]:
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
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "victims": {i.t0: s.victims[i.t0] for i in s.planned if a <= i.t0 < b},
                "tables": {
                    # (id, start, end, status, client ok, refused, deltas per shard, applied at per shard,
                    #  resolved at (None: still in doubt; -1: never prepared), prepared at per shard, client end)
                    "txns": s.settle(a, b),
                    # (sent, src, dest, arrived or None if lost, kind)
                    "msgs": s.messages(a, b),
                    # (time, locks held per shard, in doubt per shard, down bits, cut bits, money drift)
                    "state": _take(s.state, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
