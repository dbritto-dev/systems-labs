"""Lab paxos_consensus: one endless run on virtual time, handed out a minute at a time.

5 nodes on a simulated network (~20 ms per message) keep a replicated log: slot 0, 1, 2, ...
each holds one command (a config change, a new number each). Clients send ~`rate` commands a
second to a node: a random one (a load balancer spreads them), or the leader once a node has
named it. A node answers `command_ok` once the command is decided in some slot and applied (every
slot before it decided too); a client tries another node after 0.5 s and gives up after 2 s.

Incidents come at random, like in production: the leader (or the busiest proposer) crashes in
the middle of a round, another node (an acceptor) crashes, the network loses and delays messages,
a partition cuts the leader off with one node, or the leader stops for a few seconds (a GC pause)
and comes back still sure it leads: two proposers duel. A crashed node restarts with what Paxos
keeps on disk (promised, accepted, decided). The first incident is always the leader crashing
mid-round at 0:20 (back at 0:30): it stops reading the network, one slot's accepts are lost with
it, and the next two slots' accepts reach everyone: those two are chosen and nobody knows it, with
a gap before them.

The checker watches every node's `decided` and `accepted` (outside the network, not counted as
traffic): two values decided in one slot, or a value decided that differs from the one a majority
of acceptors accepted (chosen), is a disagreement. A command acknowledged to its client is lost if
the log the nodes agree on (the value most nodes decided in each slot) does not hold it.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import random
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Delivery, Network
from core.vtime import VirtualRun, now
from labs.paxos_consensus import lab

LAB = "paxos_consensus"
NAMES = ("PaxosNode",)
PIECE = 60.0
DRAIN = 20.0
LATENCY = 0.02
PROBE = 0.05  # how often the checker looks at roles and ballots
TRY_TIMEOUT = 0.5  # one attempt of a client
NO_LEADER_WAIT = 0.2  # a client waits this long when a node knows no leader
ARMED = 1.0  # a crash waiting for its moment (mid-round) happens anyway after this long
MID_ROUND = 2  # a leader dying mid-round loses one slot's accepts, then gets the next 2 slots' out
KEEP_SLOTS = 4000  # slots the checker remembers (older ones are settled)
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "proposer_crash", 1.0, "oom_killed")
KINDS = [
    Kind("proposer_crash", 0.25, median=6.0, shortest=3.0, longest=12.0, causes=(
        "oom_killed", "kernel_panic", "spot_reclaimed")),
    Kind("acceptor_crash", 0.2, median=6.0, shortest=3.0, longest=15.0, causes=(
        "host_reboot", "disk_failed", "hypervisor_fault")),
    Kind("lossy", 0.2, median=8.0, shortest=5.0, longest=20.0, severity=(0.1, 0.25), causes=(
        "flapping_link", "nic_firmware", "congested_link")),
    Kind("partition", 0.2, median=8.0, shortest=4.0, longest=20.0, causes=(
        "tor_switch", "zone_link", "firewall_rule")),
    Kind("duel", 0.15, median=2.5, shortest=1.5, longest=4.0, causes=(
        "gc_pause", "vm_migration", "disk_stall")),
]
MEAN_GAP = 25.0
QUIET = 25.0  # calm after an incident: 15 s measured before the next one, 5 s to judge the last

# Roles in the trace.
FOLLOWER, CANDIDATE, LEADER, DOWN, PAUSED = range(5)
ROLES = {"follower": FOLLOWER, "candidate": CANDIDATE, "leader": LEADER}
# Kinds of message.
PROPOSE, PREPARE, PROMISE, ACCEPT, ACCEPTED, DECIDE, OTHER = range(7)
KIND_OF = {"propose": PROPOSE, "prepare": PREPARE, "promise": PROMISE, "prepare_ok": PROMISE,
           "accept": ACCEPT, "accepted": ACCEPTED, "accept_ok": ACCEPTED, "decide": DECIDE}
# Kinds of checker event.
DISAGREE = 0


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Net(Network):
    """The network, plus lost messages (a lossy link), dead nodes (what reaches them is lost), and
    a record of which node proposed last (the busiest proposer)."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.loss = 0.0
        self.last_proposer: str | None = None

    def send(self, src: str, dest: str, body) -> None:
        kind = KIND_OF.get(str(body.get("type", "")), OTHER)
        if kind in (PROPOSE, PREPARE, ACCEPT) and src in self.nodes and self.nodes[src].is_server:
            self.last_proposer = src
        both = src != dest and dest in self.nodes and src in self.nodes and \
            self.nodes[src].is_server and self.nodes[dest].is_server
        if both and self.loss and self.rng.random() < self.loss:
            self.log.append(Delivery(now(), src, dest, kind, dropped=True))  # type: ignore[arg-type]
            return
        super().send(src, dest, body)
        self.log[-1].type = kind  # type: ignore[assignment]  # the picture wants the kind, not the word

    def _arrive(self, msg, rec) -> None:
        if getattr(self.nodes.get(msg.dest), "dead", False):
            rec.dropped = True
            return
        super()._arrive(msg, rec)


class _Watched(dict):
    """A node's `decided` or `accepted`: every write is reported to the checker."""

    __slots__ = ("hook",)

    def __init__(self, data, hook) -> None:
        super().__init__(data)
        self.hook = hook

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self.hook(key, value)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, *args, **kw) -> None:
        for key, value in dict(*args, **kw).items():
            self[key] = value


def _managed(cls, sim: "_Sim"):
    """Your node, plus what the scenario needs: crash, restart, pause, and the checker's eyes."""

    class Managed(cls):
        def __init__(self, node_id: str, node_ids: list[str]) -> None:
            self._tasks: list = []
            self.dead = False
            self.paused = False
            self.held: list = []  # what a paused node sends and receives, for when it wakes up
            self.die_mid_round = False
            self._lost_slot = None
            self._sent_next: set[str] = set()
            super().__init__(node_id, node_ids)

        # The checker sees every write to decided and accepted.
        @property
        def decided(self):
            return self._decided

        @decided.setter
        def decided(self, data) -> None:
            self._decided = _Watched(data, lambda slot, value: sim.on_decided(self, slot, value))

        @property
        def accepted(self):
            return self._accepted

        @accepted.setter
        def accepted(self, data) -> None:
            self._accepted = _Watched(data, lambda slot, value: sim.on_accepted(self, slot, value))

        def every(self, seconds, fn):
            task = super().every(seconds, fn)
            self._tasks.append((task, None))
            return task

        def spawn(self, coro):
            if self.dead:
                coro.close()
                return None
            task = super().spawn(coro)
            self._tasks.append((task, coro))
            if len(self._tasks) > 512:
                self._tasks = [(t, c) for t, c in self._tasks if not t.done()]
            return task

        def send(self, dest, body):
            if self.dead:
                return
            if self.paused:
                self.held.append((True, dest, body))
                return
            if self.die_mid_round and body.get("type") in ("accept", "propose") and "slot" in body:
                if self._lost_slot is None:
                    self._lost_slot = body["slot"]
                if body["slot"] == self._lost_slot:  # still in its send buffer when it died
                    self.net.log.append(Delivery(now(), self.node_id, dest, KIND_OF[body["type"]], dropped=True))
                    return
                super().send(dest, body)
                if dest != self.node_id:
                    self._sent_next.add((body["slot"], dest))
                if len(self._sent_next) >= MID_ROUND * (len(self.node_ids) - 1):  # the next slots went out
                    sim.kill(self)
                return
            super().send(dest, body)

        def _deliver(self, msg):
            if self.dead or (self.die_mid_round and msg.src in self.net.nodes and self.net.nodes[msg.src].is_server):
                return  # dying: it no longer reads what the other nodes send
            if self.paused:
                self.held.append((False, None, msg))
                return
            super()._deliver(msg)

        def kill(self) -> None:
            self.dead = True
            for task, coro in self._tasks:
                task.cancel()
                if coro is not None and inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
                    coro.close()  # it never started: nothing to clean up
            self._tasks = []

        def wake(self) -> None:
            """The pause is over: what it sent while paused goes out now, then what it received."""
            self.paused = False
            held, self.held = self.held, []
            for out, dest, item in held:
                if self.dead:
                    return
                if out:
                    self.send(dest, item)
                else:
                    self._deliver(item)

    Managed.__name__ = cls.__name__
    return Managed


class _Slot:
    """What the checker knows about one slot."""

    __slots__ = ("first", "votes", "chosen", "acc", "bad")

    def __init__(self) -> None:
        self.first = None  # the first value any node decided here
        self.votes: dict = {}  # value -> nodes that decided it (bits)
        self.chosen = None  # the value a majority of acceptors accepted (with one ballot)
        self.acc: dict = {}  # (ballot, value) -> acceptors that accepted it (bits)
        self.bad = False  # a disagreement was reported

    def agreed(self):
        """The value most nodes decided here (ties: the first one decided)."""
        if not self.votes:
            return None
        top = max(bin(m).count("1") for m in self.votes.values())
        if bin(self.votes.get(self.first, 0)).count("1") == top:
            return self.first
        return next(v for v, m in self.votes.items() if bin(m).count("1") == top)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = _Net(latency=LATENCY, jitter=0.3, seed=seed)
        self.ids = [f"n{i}" for i in range(lab.NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.cls = _managed(code.PaxosNode, self)
        self.nodes: dict[str, object] = {}  # built in setup(), inside the simulation (they start timers)
        self.client = Client("c1")
        self.net.join(self.client)
        self.rng = random.Random(seed * 11 + 3)
        self.planned: list[Planned] = []
        self.victims: dict[float, list[int]] = {}
        self.guess: str | None = None  # the leader a node named to the clients
        self.ops: list[tuple] = []  # (start, value, end, ok, node)
        self.state: list[tuple] = []  # (t, roles, ballots, applied)
        self.events: list[tuple] = []  # (t, slot, node, kind)
        self.slots: dict[int, _Slot] = {}
        self.where: dict[int, set[int]] = {}  # value -> slots some node decided it in
        self.top = 0  # the highest slot seen

    # ---- the nodes' lives

    def boot(self, node_id: str, old=None):
        node = self.cls(node_id, self.ids)
        for name in ("promised", "accepted", "decided", "role"):
            if not hasattr(node, name):
                raise AttributeError(lab_text(LAB).STRINGS["no_state"].format(name=name))
        if old is not None:  # a restart keeps only what Paxos keeps on disk
            node.promised = old.promised
            node.accepted = dict(old.accepted)
            node.decided = dict(old.decided)
        self.net.join(node)
        self.nodes[node_id] = node
        return node

    def kill(self, node) -> None:
        if not node.dead:
            node.kill()

    async def setup(self) -> None:
        for n in self.ids:
            self.boot(n)

    def leader(self) -> str | None:
        alive = [n for n in self.nodes.values() if not n.dead and not n.paused and n.role == "leader"]
        if alive:
            return max(alive, key=lambda n: (getattr(n, "ballot", 0) or 0, n.promised)).node_id
        last = self.net.last_proposer
        return last if last in self.nodes and not self.nodes[last].dead else None

    # ---- what the checker sees

    def slot(self, slot) -> _Slot | None:
        if not isinstance(slot, int):
            return None
        info = self.slots.get(slot)
        if info is None:
            info = self.slots[slot] = _Slot()
            self.top = max(self.top, slot)
        return info

    def disagree(self, info: _Slot, slot: int, node: int) -> None:
        if not info.bad:
            info.bad = True
            self.events.append((now(), slot, node, DISAGREE))

    def on_decided(self, node, slot, value) -> None:
        info = self.slot(slot)
        if info is None:
            return
        i = self.index.get(node.node_id, 0)
        try:
            info.votes[value] = info.votes.get(value, 0) | 1 << i
            self.where.setdefault(value, set()).add(slot)
        except TypeError:  # an unhashable value: nothing to compare
            return
        if info.first is None:
            info.first = value
        elif value != info.first:
            self.disagree(info, slot, i)
        if info.chosen is not None and value != info.chosen:
            self.disagree(info, slot, i)

    def on_accepted(self, node, slot, entry) -> None:
        info = self.slot(slot)
        try:
            ballot, value = entry[0], entry[1]
            key = (ballot, value)
            hash(key)
        except (TypeError, IndexError, KeyError):
            return
        if info is None:
            return
        i = self.index.get(node.node_id, 0)
        mask = info.acc.get(key, 0) | 1 << i
        info.acc[key] = mask
        if bin(mask).count("1") >= lab.NODES // 2 + 1:
            if info.chosen is None:
                info.chosen = value
                if info.first is not None and info.first != value:
                    self.disagree(info, slot, i)
            elif info.chosen != value:
                self.disagree(info, slot, i)

    def kept(self, value) -> bool:
        """Is an acknowledged command in the log the nodes agree on?"""
        return any(self.slots[s].agreed() == value for s in self.where.get(value, ()) if s in self.slots)

    def forget(self) -> None:
        old = self.top - KEEP_SLOTS
        for s in [s for s in self.slots if s < old]:
            del self.slots[s]

    # ---- clients

    async def command(self, value: int) -> None:
        start = now()
        target = self.guess or self.rng.choice(self.ids)
        ok, silent = False, set()  # nodes that did not answer this command
        while not ok and now() - start < lab.DEADLINE:
            try:
                reply = await self.client.rpc(target, {"type": "command", "value": value},
                                              timeout=max(0.01, min(TRY_TIMEOUT, start + lab.DEADLINE - now())))
            except Exception:  # noqa: BLE001 - a timeout or an error reply: try another node
                silent.add(target)
                if self.guess == target:
                    self.guess = None
                target = self.other(target, silent)
                continue
            if reply.get("type") == "command_ok":
                ok = True
            elif reply.get("leader") in self.index and reply["leader"] not in silent | {target}:
                target = self.guess = reply["leader"]
            else:  # no leader known yet (or one that did not answer)
                if self.guess == target:
                    self.guess = None
                target = self.other(target, silent)
                await asyncio.sleep(NO_LEADER_WAIT)
        self.ops.append((start, value, now(), ok, self.index[target]))

    def other(self, target: str, silent: set[str]) -> str:
        return self.rng.choice([n for n in self.ids if n != target and n not in silent]
                               or [n for n in self.ids if n != target])

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11)
        for value, t in enumerate(arrivals(self.rate, self.seed, 0.5, rng), start=1):
            await asyncio.sleep(t - now())
            asyncio.ensure_future(self.command(value))

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            leader = self.leader() or self.rng.choice(self.ids)
            if inc.kind == "proposer_crash":
                self.victims[inc.t0] = [self.index[leader]]
                node = self.nodes[leader]
                node.die_mid_round = True  # it dies while sending one slot's accepts
                await asyncio.sleep(ARMED)
                self.kill(node)  # if its moment did not come
                await asyncio.sleep(inc.t1 - now())
                self.boot(leader, node)
            elif inc.kind == "acceptor_crash":
                who = self.rng.choice([n for n in self.ids if n != leader])
                self.victims[inc.t0] = [self.index[who]]
                node = self.nodes[who]
                self.kill(node)
                await asyncio.sleep(inc.t1 - now())
                self.boot(who, node)
            elif inc.kind == "partition":
                buddy = self.rng.choice([n for n in self.ids if n != leader])
                small = {leader, buddy}
                self.victims[inc.t0] = [self.index[leader], self.index[buddy]]
                self.net.partition([small, set(self.ids) - small])
                await asyncio.sleep(inc.t1 - now())
                self.net.heal()
            elif inc.kind == "duel":
                self.victims[inc.t0] = [self.index[leader]]
                node = self.nodes[leader]
                node.paused = True  # it stops; the others elect someone; then it wakes up still leading
                await asyncio.sleep(inc.t1 - now())
                if not node.dead:
                    node.wake()
            else:  # lossy
                self.victims[inc.t0] = []
                self.net.loss, self.net.latency = inc.severity, LATENCY * 2
                await asyncio.sleep(inc.t1 - now())
                self.net.loss, self.net.latency = 0.0, LATENCY

    # ---- the checker (outside the network)

    async def checker(self) -> None:
        while True:
            await asyncio.sleep(PROBE)
            roles, ballots, applied = [], [], []
            for n in self.ids:
                node = self.nodes[n]
                if node.dead:
                    roles.append(DOWN)
                elif node.paused:
                    roles.append(PAUSED)
                else:
                    roles.append(ROLES.get(getattr(node, "role", ""), FOLLOWER))
                ballot = getattr(node, "ballot", 0) if roles[-1] == LEADER else node.promised
                ballots.append(int(ballot) if isinstance(ballot, int) else 0)
                applied.append(len(node.decided))
            self.state.append((now(), tuple(roles), tuple(ballots), tuple(applied)))

    # ---- handing out a minute

    def settle(self, a: float, b: float) -> list[tuple]:
        """Commands that started in [a, b): (start, value, end, ok, node, kept)."""
        out = []
        for row in _take(self.ops, 0, a, b):
            start, value, end, ok, node = row
            out.append((start, value, end, ok, node, (not ok) or self.kept(value)))
        for value in [v for v in self.where if v <= (out[-1][1] if out else 0) - 2000]:
            del self.where[value]
        return out

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between two nodes sent in [a, b): (sent, src, dest, arrived or None, kind)."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.src in self.index and d.dest in self.index and d.src != d.dest and d.sent >= a:
                out.append((d.sent, self.index[d.src], self.index[d.dest], d.arrived, d.type))
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
            s.forget()
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "victims": {t0: v for t0, v in s.victims.items() if a <= t0 < b},
                "tables": {
                    # (start, value, end, ok, node it last tried, kept: in the agreed log if acknowledged)
                    "ops": s.settle(a, b),
                    # (sent, src, dest, arrived or None if lost, kind)
                    "msgs": s.messages(a, b),
                    # (time, role of each node, ballot of each node, decided slots of each node)
                    "state": _take(s.state, 0, a, b),
                    # (time, slot, node, kind): two values decided in one slot
                    "events": _take(s.events, 0, a, b),
                },
            }
    finally:
        for node in s.nodes.values():  # nothing new starts while the run shuts down
            node.kill()
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
