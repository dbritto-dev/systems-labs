"""Lab chain_replication: one endless run on virtual time, handed out a minute at a time.

A key/value store replicated on 4 nodes (n0..n3) on a simulated network (~30 ms per message). A
configuration master (reliable, like ZooKeeper or etcd) holds the chain, head first, and tells every
node when it changes. Clients learn the chain from the master: they send writes (`put`) to the head
and reads (`get`) to `read_from(chain, rng)`.

Incidents, like in production: the head, the tail or a middle node crashes (the master notices after
its session times out, 1 s, and drops it from the chain), or a node turns slow and backs the chain up
(the master ejects it after 2 s and fences it: it restarts empty). When the incident ends the node
comes back empty and joins again: the master asks it to copy the tail's state (the copy takes ~1 s
on the wire), then adds it as the new tail. The first incident always crashes the middle node n1 at
0:20; it is back at 0:30.

The checker looks inside the nodes (their `store`), outside the network: a read is stale when it
misses a write acknowledged before it started, or returns an older value than a read that ended
before it started; an acknowledged write is lost when no live node in the chain holds it any more.
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
from core.net import Client, Message, Network, RPCError
from core.vtime import VirtualRun, now
from labs.chain_replication import lab

LAB = "chain_replication"
NAMES = ("ChainNode", "read_from")
PIECE = 60.0
DRAIN = 15.0  # simulate this far past a minute before handing it out
LATENCY = 0.03  # seconds per message
KEYS = 100
CLIENT_TIMEOUT = 2.0
CHECK_EVERY = 0.25  # how often the checker looks at the nodes
SETTLED = 1.0  # a write acknowledged this long ago must be on every replica
SLOW_FACTOR = 8.0  # a slow node's messages take this many times longer
CONFIG_TIMEOUT = 0.5  # the master waits this long for a node to take a new chain
JOIN_TIMEOUT = 5.0  # ... and this long for a node to copy the tail's state
JOIN_RETRY = 1.0  # a node that could not join is asked again after this long

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "middle", 1.0, "oom_kill")
KINDS = [
    Kind("head", 0.25, median=8.0, shortest=4.0, longest=20.0, causes=("kernel_panic", "bad_deploy", "host_reboot")),
    Kind("middle", 0.25, median=8.0, shortest=4.0, longest=20.0, causes=("oom_kill", "disk_failure", "host_reboot")),
    Kind("tail", 0.25, median=8.0, shortest=4.0, longest=20.0, causes=("oom_kill", "kernel_panic", "power_supply")),
    Kind("slow", 0.25, median=10.0, shortest=6.0, longest=20.0, causes=("gc_pause", "disk_full", "noisy_neighbour")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # calm after an incident: the node joins again, 5 s to judge it, 15 s of baseline

PUT, GET = 0, 1  # operation kinds
# Message kinds, for the pictures.
M_PUT, M_GET, M_WRITE, M_ACK, M_REPLICATE, M_SNAPSHOT, M_ANSWER, M_OTHER = range(8)
_KINDS = {"put": M_PUT, "get": M_GET, "write": M_WRITE, "ack": M_ACK, "replicate": M_REPLICATE,
          "snapshot_ok": M_SNAPSHOT, "put_ok": M_ANSWER, "get_ok": M_ANSWER}


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, chain: list[str], seed: int) -> str:
    """Which node the incident hits, by its place in the chain (the first one always hits n1)."""
    if inc.t0 == FIRST.t0:
        return "n1"
    rng = random.Random(f"{seed}:{inc.t0}:victim")
    if inc.kind == "head" or len(chain) == 1:
        return chain[0]
    if inc.kind == "tail":
        return chain[-1]
    if inc.kind == "middle" and len(chain) > 2:
        return rng.choice(chain[1:-1])
    return rng.choice(chain)


class _Net(Network):
    """The network, plus dead nodes (what arrives at one is lost) and one slow node."""

    def __init__(self, seed: int) -> None:
        super().__init__(latency=LATENCY, jitter=0.2, seed=seed)
        self.slow: str | None = None

    def send(self, src: str, dest: str, body) -> None:
        saved = self.latency
        if body.get("type") == "snapshot_ok":
            self.latency = lab.COPY  # the whole store on the wire
        elif self.slow is not None and self.slow in (src, dest):
            self.latency = saved * SLOW_FACTOR
        try:
            super().send(src, dest, body)
        finally:
            self.latency = saved
        rec = self.log[-1]
        rec.type = _KINDS.get(str(body.get("type", "")), M_OTHER)  # type: ignore[assignment]

    def _arrive(self, msg: Message, rec) -> None:
        if getattr(self.nodes.get(msg.dest), "dead", False):
            rec.dropped = True
            return
        super()._arrive(msg, rec)


def _managed(cls):
    """Your node, plus what the scenario needs to crash it: a dead node sends nothing, hears nothing."""

    class Managed(cls):
        def __init__(self, *args) -> None:
            self._tasks: list = []
            self.dead = False
            super().__init__(*args)

        def _track(self, task, coro=None):
            self._tasks.append((task, coro))
            if len(self._tasks) > 256:
                self._tasks = [(t, c) for t, c in self._tasks if not t.done()]
            return task

        async def _run(self, coro) -> None:
            try:
                await coro
            except (TimeoutError, RPCError):
                pass  # an RPC inside a handler went unanswered: the handler's business
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
            if not self.dead:
                super().send(dest, body)

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
                    coro.close()
            self._tasks = []

    Managed.__name__ = cls.__name__
    return Managed


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = _Net(seed)
        self.ids = [f"n{i}" for i in range(lab.NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.code = code
        self.cls = _managed(code.ChainNode)
        self.nodes: dict[str, object] = {}
        self.client = Client("c1")
        self.master = Client("master")
        self.net.join(self.client)
        self.net.join(self.master)
        self.chain: list[str] = []  # the master's chain
        self.seen: list[str] = []  # the chain the clients know (once every node has taken it)
        self.joining: set[str] = set()  # nodes copying the tail's state
        self.lock = asyncio.Lock()  # the master changes one chain at a time
        self.planned: list[Planned] = []
        self.victims: dict[float, int] = {}
        self.slow: str | None = None
        self.ops: dict[int, list] = {}  # op id -> [start, kind, key, value, end, ok, stale, lost, node]
        self.acked: dict[str, tuple[float, int]] = {}  # key -> (ack time, newest acknowledged value)
        self.history: dict[str, list[tuple[float, int, int]]] = {}  # key -> [(ack time, value, op id)]
        self.reads: dict[str, list[tuple[float, int]]] = {}  # key -> [(end, value a read returned)]
        self.busy: set[str] = set()  # keys with a write in flight
        self.lost_rows: list[tuple] = []  # (time found, key, value)
        self.lost_seen: set[tuple[str, int]] = set()
        self.state: list[tuple] = []
        self._value = itertools.count(1)
        self._op = itertools.count()

    # ---- the nodes' lives

    def boot(self, node_id: str) -> None:
        node = self.cls(node_id, self.ids)
        if not hasattr(node, "store"):
            raise AttributeError(lab_text(LAB).STRINGS["no_store"])
        self.nodes[node_id] = node
        self.net.join(node)

    def kill(self, node_id: str) -> None:
        node = self.nodes[node_id]
        if not node.dead:
            node.kill()

    def alive(self, node_id: str) -> bool:
        return not self.nodes[node_id].dead

    # ---- the master

    async def push(self, chain: list[str]) -> None:
        """Tell every live node in the chain, tail first, then the clients."""
        self.chain = list(chain)
        for n in reversed(chain):
            if self.alive(n):
                try:
                    await self.master.rpc(n, {"type": "config", "chain": list(chain)}, timeout=CONFIG_TIMEOUT)
                except (TimeoutError, RPCError):
                    pass
        self.seen = list(chain)

    async def remove(self, node_id: str) -> None:
        async with self.lock:
            if node_id in self.chain:
                await self.push([n for n in self.chain if n != node_id])

    async def add(self, node_id: str) -> None:
        """Ask the node to copy the tail's state; once it has, it is the new tail."""
        while self.alive(node_id) and node_id not in self.chain:
            async with self.lock:
                self.joining.add(node_id)
                try:
                    tail = self.chain[-1]
                    await self.master.rpc(node_id, {"type": "join", "tail": tail}, timeout=JOIN_TIMEOUT)
                    if self.alive(node_id) and self.chain and self.chain[-1] == tail:
                        await self.push([*self.chain, node_id])
                        return
                except (TimeoutError, RPCError):
                    pass
                finally:
                    self.joining.discard(node_id)
            await asyncio.sleep(JOIN_RETRY)

    async def setup(self) -> None:
        for n in self.ids:
            self.boot(n)
        await self.push(list(self.ids))

    # ---- clients

    async def _call(self, oid: int, kind: int, node: str, key: str, value: int = -1) -> None:
        start = now()
        body = {"type": "put", "key": key, "value": value} if kind == PUT else {"type": "get", "key": key}
        got, ok = None, False
        try:
            reply = await self.client.rpc(node, body, timeout=CLIENT_TIMEOUT)
            ok = True
            got = reply.get("value")
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the client gives up
            ok = False
        end = now()
        row = self.ops[oid]
        row[4], row[5] = end, ok
        if kind == PUT:
            self.busy.discard(key)
            if ok:
                if key not in self.acked or value > self.acked[key][1]:
                    self.acked[key] = (end, value)
                h = self.history.setdefault(key, [])
                h.append((end, value, oid))
                del h[:-4]
        elif ok:
            # It must see every write acknowledged before it started, and anything a read that ended
            # before it started saw (a value that read showed cannot go away).
            acked = max((v for t, v, _ in self.history.get(key, ()) if t < start), default=None)
            seen = max((v for t, v in self.reads.get(key, ()) if t < start), default=None)
            expected = max((v for v in (acked, seen) if v is not None), default=None)
            row[6] = expected is not None and (not isinstance(got, int) or got < expected)
            row[3] = got if isinstance(got, int) else -1
            if isinstance(got, int):
                r = self.reads.setdefault(key, [])
                r.append((end, got))
                del r[:-4]

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            chain = self.seen
            if not chain:
                continue
            key = f"k{rng.randrange(KEYS)}"
            oid = next(self._op)
            if rng.random() < 0.5 and key not in self.busy:
                self.busy.add(key)
                value = next(self._value)
                node = chain[0]
                self.ops[oid] = [now(), PUT, int(key[1:]), value, None, False, False, False, self.index[node]]
                asyncio.ensure_future(self._call(oid, PUT, node, key, value))
            else:
                node = self.code.read_from(list(chain), rng)
                if node not in self.index:
                    raise ValueError(lab_text(LAB).STRINGS["bad_read_from"].format(node=node))
                self.ops[oid] = [now(), GET, int(key[1:]), -1, None, False, False, False, self.index[node]]
                asyncio.ensure_future(self._call(oid, GET, node, key))

    # ---- incidents

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            sick = victim(inc, self.chain or self.ids, self.seed)
            self.victims[inc.t0] = self.index[sick]
            if inc.kind == "slow":
                self.slow = self.net.slow = sick
                await asyncio.sleep(lab.EJECT)
                self.kill(sick)  # the master ejects it and fences it: it restarts empty
                await self.remove(sick)
            else:
                self.kill(sick)
                await asyncio.sleep(lab.DETECT)  # its session with the master times out
                await self.remove(sick)
            await asyncio.sleep(max(0.0, inc.t1 - now()))
            self.slow = self.net.slow = None
            self.boot(sick)  # back, empty
            asyncio.ensure_future(self.add(sick))

    # ---- the checker (outside the network)

    async def checker(self) -> None:
        while True:
            await asyncio.sleep(CHECK_EVERY)
            t = now()
            live = [n for n in self.chain if self.alive(n)]
            stores = [self.nodes[n].store for n in live]
            behind = [0] * lab.NODES
            for key, (at, value) in self.acked.items():
                held = [s.get(key) for s in stores]
                if not any(isinstance(v, int) and v >= value for v in held) and (key, value) not in self.lost_seen:
                    self.lost_seen.add((key, value))
                    self.lost_rows.append((t, int(key[1:]), value))
                    for _, v, oid in self.history.get(key, ()):
                        if v == value and oid in self.ops:
                            self.ops[oid][7] = True
                if t - at >= SETTLED:
                    for n, v in zip(live, held):
                        if not (isinstance(v, int) and v >= value):
                            behind[self.index[n]] += 1
            down = sum(1 << i for i, n in enumerate(self.ids) if not self.alive(n))
            joining = sum(1 << self.index[n] for n in self.joining)
            sent = [0] * lab.NODES  # per node: writes passed down, not yet acknowledged
            for n in live[:-1]:
                sent[self.index[n]] = len(getattr(self.nodes[n], "sent", ()) or ())
            inflight = sum(sent)
            self.state.append((t, tuple(self.index[n] for n in self.chain), down, joining, tuple(behind),
                               self.index[self.slow] if self.slow else -1, inflight, tuple(sent)))

    # ---- handing out a minute

    def take_ops(self, a: float, b: float) -> list[tuple]:
        out = []
        for oid in [k for k, r in self.ops.items() if r[0] < b and r[4] is not None]:
            r = self.ops.pop(oid)
            if r[0] >= a:
                out.append(tuple(r))
        return sorted(out)

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages sent in [a, b): (sent, src, dest, arrived or None, kind); -1 is the clients."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.sent < a or d.src == "master" or d.dest == "master":
                continue
            out.append((d.sent, self.index.get(d.src, -1), self.index.get(d.dest, -1), d.arrived, d.type))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 20.0) -> Iterator[dict]:
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
                "victims": {i.t0: s.victims[i.t0] for i in s.planned if a <= i.t0 < b and i.t0 in s.victims},
                "tables": {
                    # (start, kind, key, value, end, ok, stale, lost, node)
                    "ops": s.take_ops(a, b),
                    # (sent, src, dest, arrived or None if lost, kind); -1 = the clients
                    "msgs": s.messages(a, b),
                    # (time, chain as node indices, down bits, joining bits, behind per node, slow node or -1,
                    #  writes in flight down the chain, the same per node)
                    "state": _take(s.state, 0, a, b),
                    # (time found, key, value): acknowledged writes no live node in the chain holds
                    "lost": _take(s.lost_rows, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
