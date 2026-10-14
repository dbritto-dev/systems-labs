"""Lab raft_consensus: one endless run on virtual time, handed out a minute at a time.

5 nodes on a simulated network (~20 ms per message). Clients send ~`rate` commands/s
(a new unique number each) to the node they think is the leader; a follower answers with
a redirect, and the client tries again (a command gives up after 2 s). Your `RaftNode`
must elect one leader, replicate every command to a majority before answering, and never
lose a committed command.

Incidents come at random, like in production: the leader is cut off with one follower (a
minority partition), the leader's host crashes and restarts later (keeping only what Raft
persists: current_term, voted_for and log), or the network gets slow. The first one always
cuts the leader off at 0:20-0:30.

The checker reads every node's role, current_term and log outside the network (not counted
as traffic): a command is committed once a majority holds it at the same position.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import random
from collections import Counter
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Network
from core.vtime import VirtualRun, now

LAB = "raft_consensus"
NAMES = ("RaftNode",)
PIECE = 60.0
DRAIN = 20.0
NODES = 5
LATENCY = 0.02
PROBE = 0.05  # how often the checker looks at roles and terms
LOG_PROBE = 0.1  # how often it looks at the logs
WINDOW = 300  # log positions it re-checks each time (older ones are settled)
TRY_TIMEOUT = 0.5  # one attempt of a client
OP_DEADLINE = 2.0  # a command gives up after this long
NO_LEADER_WAIT = 0.2  # a client waits this long when no node knows the leader
HEAL_LAG = 0.5  # a partition heals one way first: the cut-off side is heard before it hears
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "partition", 1.0, "tor_switch")
KINDS = [
    Kind("partition", 0.45, median=8.0, shortest=4.0, longest=20.0, causes=(
        "tor_switch", "zone_link", "firewall_rule")),
    Kind("crash", 0.4, median=6.0, shortest=3.0, longest=15.0, causes=(
        "kernel_panic", "oom_killed", "host_reboot")),
    Kind("slow", 0.15, median=8.0, shortest=5.0, longest=20.0, severity=(2.0, 4.0), causes=(
        "congested_link", "noisy_neighbour")),
]
MEAN_GAP = 25.0
QUIET = 25.0  # calm before the next one: 15 s measured before it, 5 s to judge the last

# Roles in the trace.
FOLLOWER, CANDIDATE, LEADER, DOWN = range(4)
ROLES = {"follower": FOLLOWER, "candidate": CANDIDATE, "leader": LEADER}
# Kinds of message.
APPEND, VOTE, OTHER = range(3)
# Kinds of checker event.
COMMITTED, LOST, TWO_LEADERS = range(3)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class _Net(Network):
    """A network whose partitions heal one way first: for HEAL_LAG seconds the cut-off side
    can send to the others, but not hear back (routes converge one direction at a time)."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.deaf: set[str] = set()

    def cut(self, a: str, b: str) -> bool:
        if b in self.deaf and a not in self.deaf and self.nodes[a].is_server:
            return True
        return super().cut(a, b)


def _managed(cls):
    """Your node, plus what the scenario needs to crash and restart it."""

    class Managed(cls):
        def __init__(self, node_id: str, node_ids: list[str]) -> None:
            self._tasks: list = []
            self.dead = False
            super().__init__(node_id, node_ids)

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
            if not self.dead:
                super().send(dest, body)

        def _deliver(self, msg):
            if not self.dead:
                super()._deliver(msg)

        def kill(self) -> None:
            self.dead = True
            for task, coro in self._tasks:
                task.cancel()
                if coro is not None and inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
                    coro.close()  # it never started: nothing to clean up

    Managed.__name__ = cls.__name__
    return Managed


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = _Net(latency=LATENCY, jitter=0.3, seed=seed)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.cls = _managed(code.RaftNode)
        self.nodes: dict[str, object] = {}  # built in setup(), inside the simulation (they start timers)
        self.client = Client("c1")
        self.net.join(self.client)
        self.rng = random.Random(seed * 11 + 3)
        self.planned: list[Planned] = []
        self.victims: dict[float, list[int]] = {}
        self.guess: str | None = None
        self.ops: list[tuple] = []  # (start, value, end, ok, node)
        self.state: list[tuple] = []  # (t, roles, terms)
        self.events: list[tuple] = []  # (t, value or term, index or node, kind)
        self.committed: dict[int, tuple[int, int]] = {}  # position -> (term, command) once committed
        self.lost: set[int] = set()
        self.held: dict[int, int] = {}  # position -> nodes seen holding its committed entry (bits)
        self.seen_two: set[int] = set()

    def boot(self, node_id: str, old=None):
        node = self.cls(node_id, self.ids)
        for name in ("current_term", "voted_for", "log", "role"):
            if not hasattr(node, name):
                raise AttributeError(lab_text(LAB).STRINGS["no_state"].format(name=name))
        if old is not None:  # a restart keeps only what Raft persists
            node.current_term, node.voted_for, node.log = old.current_term, old.voted_for, list(old.log)
        self.net.join(node)
        self.nodes[node_id] = node
        return node

    async def setup(self) -> None:
        for n in self.ids:
            self.boot(n)

    def leader(self) -> str | None:
        alive = [n for n in self.nodes.values() if not n.dead and n.role == "leader"]
        return max(alive, key=lambda n: n.current_term).node_id if alive else None

    # ---- clients

    async def command(self, value: int) -> None:
        start = now()
        target = self.guess or self.rng.choice(self.ids)
        ok, silent = False, set()  # nodes that did not answer this command
        while not ok and now() - start < OP_DEADLINE:
            try:
                reply = await self.client.rpc(target, {"type": "command", "value": value},
                                              timeout=max(0.01, min(TRY_TIMEOUT, start + OP_DEADLINE - now())))
            except Exception:  # noqa: BLE001 - a timeout or an error reply: try another node
                silent.add(target)
                if self.guess == target:
                    self.guess = None
                target = self.other(target, silent)
                continue
            if reply.get("type") == "command_ok":
                ok, self.guess = True, target
            elif reply.get("leader") in self.index and reply["leader"] not in silent | {target}:
                target = reply["leader"]
            else:  # no leader known yet (or one that did not answer)
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
            if inc.kind == "partition":
                buddy = self.rng.choice([n for n in self.ids if n != leader])
                small = {leader, buddy}
                self.victims[inc.t0] = [self.index[leader], self.index[buddy]]
                self.net.partition([small, set(self.ids) - small])
                await asyncio.sleep(inc.t1 - now())
                self.net.heal()
                self.net.deaf = small
                await asyncio.sleep(HEAL_LAG)
                self.net.deaf = set()
            elif inc.kind == "crash":
                self.victims[inc.t0] = [self.index[leader]]
                old = self.nodes[leader]
                old.kill()
                await asyncio.sleep(inc.t1 - now())
                self.boot(leader, old)
            else:
                self.victims[inc.t0] = []
                normal = self.net.latency
                self.net.latency = normal * inc.severity
                await asyncio.sleep(inc.t1 - now())
                self.net.latency = normal

    # ---- the checker (outside the network)

    async def checker(self) -> None:
        next_logs = 0.0
        while True:
            await asyncio.sleep(PROBE)
            t = now()
            roles, terms = [], []
            leaders: dict[int, list[int]] = {}
            for n in self.ids:
                node = self.nodes[n]
                role = DOWN if node.dead else ROLES.get(node.role, FOLLOWER)
                roles.append(role)
                terms.append(int(node.current_term))
                if role == LEADER:
                    leaders.setdefault(int(node.current_term), []).append(self.index[n])
            self.state.append((t, tuple(roles), tuple(terms)))
            for term, who in leaders.items():
                if len(who) > 1 and term not in self.seen_two:
                    self.seen_two.add(term)
                    self.events.append((t, term, who[0], TWO_LEADERS))
            if t >= next_logs:
                next_logs = t + LOG_PROBE
                self.check_logs(t)

    def check_logs(self, t: float) -> None:
        """Committed: a majority holds the same entry at a position. Lost: a node that held a
        committed entry no longer does (Raft never removes a committed entry from any log)."""
        logs = [self.nodes[n].log for n in self.ids]
        top = max(len(lg) for lg in logs)
        majority = NODES // 2 + 1
        for pos in range(max(0, top - WINDOW), top):
            entries = [(lg[pos].term, lg[pos].command) if pos < len(lg) else None for lg in logs]
            known = self.committed.get(pos)
            if known is not None and pos not in self.lost:
                held = self.held[pos]
                if any(held >> i & 1 and e != known for i, e in enumerate(entries)):
                    self.lost.add(pos)
                    self.events.append((t, known[1], pos, LOST))
                    continue
                for i, e in enumerate(entries):
                    if e == known:
                        held |= 1 << i
                self.held[pos] = held
            elif known is None:
                entry, n = Counter(e for e in entries if e is not None).most_common(1)[0] if any(entries) else (None, 0)
                if n >= majority:
                    self.committed[pos] = entry
                    self.held[pos] = sum(1 << i for i, e in enumerate(entries) if e == entry)
                    self.events.append((t, entry[1], pos, COMMITTED))

    def forget(self) -> None:
        """Drop what the checker knows about positions it no longer re-checks."""
        settled = max(len(n.log) for n in self.nodes.values()) - WINDOW
        for pos in [p for p in self.committed if p < settled]:
            del self.committed[pos]
            self.held.pop(pos, None)
            self.lost.discard(pos)

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between nodes sent in [a, b): (sent, src, dest, arrived or None, kind)."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.src in self.index and d.dest in self.index and d.sent >= a:
                kind = APPEND if d.type.startswith("append") else VOTE if d.type.startswith("request_vote") else OTHER
                out.append((d.sent, self.index[d.src], self.index[d.dest], d.arrived, kind))
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
                    # (start, value, end, ok, node it last tried)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped, kind)
                    "msgs": s.messages(a, b),
                    # (time, role of each node, term of each node)
                    "state": _take(s.state, 0, a, b),
                    # (time, command or term, position or node, kind): committed, lost, two leaders
                    "events": _take(s.events, 0, 0.0, b + DRAIN),
                },
            }
    finally:
        for node in s.nodes.values():  # nothing new starts while the run shuts down
            node.kill()
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
