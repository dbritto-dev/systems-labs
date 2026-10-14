"""A simulated network of nodes that talk in JSON-like messages, like Maelstrom.

This is the substrate for the distributed-systems labs (the Fly.io "Gossip Glomers"
challenges). Every node has an id ("n0", "n1", ...); clients are "c1", "c2", ...;
services are "seq-kv" and "lin-kv". A message is `Message(src, dest, body)` where
body is a dict with a "type" and, for requests, a "msg_id".

Your code is a `Node` subclass. A message of type "broadcast" calls
`async def on_broadcast(self, msg)`. Inside a handler you can:

    self.node_id, self.node_ids          who you are, and every server node
    self.reply(msg, {"type": "x_ok"})    answer a request
    self.send(dest, body)                fire and forget
    await self.rpc(dest, body, timeout)  send and wait for the reply (TimeoutError if none)
    await self.sleep(seconds)            wait (virtual time); self.now() is the clock
    self.every(seconds, coro_fn)         run something periodically
    self.spawn(coro)                     run something in the background

The network delays every message (`latency`), and partitions drop messages
between groups of nodes, both on the way and on arrival.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.vtime import now

type Body = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    src: str
    dest: str
    body: Body
    id: int = 0  # network-wide sequence number


class RPCError(Exception):
    """An error reply: code 10 not supported, 11 temporarily unavailable, 13 crash,
    20 key does not exist, 22 precondition failed."""

    def __init__(self, code: int, text: str = "") -> None:
        super().__init__(f"error {code}: {text}" if text else f"error {code}")
        self.code = code
        self.text = text


@dataclass(slots=True)
class Delivery:
    """One message on the wire, as recorded by the network."""

    sent: float
    src: str
    dest: str
    type: str
    arrived: float | None = None  # None while in flight; stays None if dropped
    dropped: bool = False


class Network:
    def __init__(self, latency: float = 0.1, jitter: float = 0.2, seed: int = 0) -> None:
        self.latency = latency
        self.jitter = jitter
        self.rng = random.Random(seed)
        self.nodes: dict[str, "Endpoint"] = {}
        self.groups: list[set[str]] | None = None  # a partition: who can talk to whom
        self.log: list[Delivery] = []
        self._ids = itertools.count(1)
        self.bugs: list[BaseException] = []

    # ---- partitions

    def partition(self, groups: list[set[str]]) -> None:
        """Only nodes in the same group can talk. Clients and services reach everyone."""
        self.groups = [set(g) for g in groups]

    def heal(self) -> None:
        self.groups = None

    def cut(self, a: str, b: str) -> bool:
        if self.groups is None or a not in self.nodes or b not in self.nodes:
            return False
        if not (self.nodes[a].is_server and self.nodes[b].is_server):
            return False
        ga = next((i for i, g in enumerate(self.groups) if a in g), None)
        gb = next((i for i, g in enumerate(self.groups) if b in g), None)
        return ga != gb

    # ---- sending

    def join(self, endpoint: "Endpoint") -> None:
        self.nodes[endpoint.node_id] = endpoint
        endpoint.net = self

    def send(self, src: str, dest: str, body: Body) -> None:
        if dest not in self.nodes:
            raise ValueError(f"{src} sent a message to {dest!r}, which does not exist")
        msg = Message(src, dest, dict(body), next(self._ids))
        rec = Delivery(now(), src, dest, str(body.get("type", "")))
        self.log.append(rec)
        if self.cut(src, dest):
            rec.dropped = True
            return
        delay = self.latency * (1 + self.jitter * (2 * self.rng.random() - 1))
        asyncio.get_running_loop().call_later(delay, self._arrive, msg, rec)

    def _arrive(self, msg: Message, rec: Delivery) -> None:
        if self.cut(msg.src, msg.dest):  # the partition started while it was on the wire
            rec.dropped = True
            return
        rec.arrived = now()
        self.nodes[msg.dest]._deliver(msg)


class Endpoint:
    """Anything with an address on the network: server nodes, clients, services."""

    is_server = False

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.net: Network = None  # type: ignore[assignment]  # set by Network.join
        self._msg_ids = itertools.count(1)
        self._waiting: dict[int, asyncio.Future] = {}

    # ---- talking

    def send(self, dest: str, body: Body) -> None:
        self.net.send(self.node_id, dest, body)

    def reply(self, request: Message, body: Body) -> None:
        body = dict(body)
        body["in_reply_to"] = request.body.get("msg_id")
        body.setdefault("type", f"{request.body.get('type', '')}_ok")
        self.send(request.src, body)

    async def rpc(self, dest: str, body: Body, timeout: float = 1.0) -> Body:
        """Send a request and wait for its reply. Raises TimeoutError, or RPCError for an error reply."""
        msg_id = next(self._msg_ids)
        fut = asyncio.get_running_loop().create_future()
        self._waiting[msg_id] = fut
        self.send(dest, {**body, "msg_id": msg_id})
        try:
            async with asyncio.timeout(timeout):
                reply = await fut
        finally:
            self._waiting.pop(msg_id, None)
        if reply.get("type") == "error":
            raise RPCError(reply.get("code", 13), reply.get("text", ""))
        return reply

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def now(self) -> float:
        """The current (virtual) time in seconds."""
        return now()

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Future:
        """Run a coroutine in the background (a bug in it is reported, a timeout is not)."""
        return asyncio.ensure_future(self._guard(coro))

    def every(self, seconds: float, fn: Callable[[], Awaitable[None]]) -> asyncio.Task:
        """Call `await fn()` every `seconds` (virtual time), forever."""

        async def loop() -> None:
            while True:
                await asyncio.sleep(seconds)
                await self._guard(fn())

        return asyncio.ensure_future(loop())

    # ---- receiving

    def _deliver(self, msg: Message) -> None:
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
        asyncio.ensure_future(self._guard(handler(msg)))

    async def _guard(self, coro: Awaitable[Any]) -> None:
        """Run a handler; a bug in it is recorded (and shown), not swallowed."""
        try:
            await coro
        except (TimeoutError, RPCError):
            pass  # an unanswered or refused RPC inside a handler is the handler's business
        # CancelledError is not caught: shutting the run down must stop every loop.
        except Exception as exc:  # noqa: BLE001
            self.net.bugs.append(exc)


class Node(Endpoint):
    """A server node. Subclass it and add `async def on_<type>(self, msg)` handlers."""

    is_server = True

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id)
        self.node_ids = list(node_ids)


class KVService(Endpoint):
    """Maelstrom's key/value services: read, write, cas.

    "lin-kv" is linearizable. "seq-kv" is sequentially consistent: a read may return an
    older value (each client sees values in order, but maybe not the latest), which is
    what makes counters on it tricky. Errors: 20 key does not exist, 22 precondition failed.
    """

    def __init__(self, name: str, stale: float = 0.0, seed: int = 0) -> None:
        super().__init__(name)
        self.data: dict[Any, Any] = {}
        self.history: dict[Any, list[tuple[float, Any]]] = {}  # key -> [(time, value)]
        self.stale = stale  # seq-kv: how far back (seconds) a read may look
        self.rng = random.Random(seed)
        self._seen: dict[tuple[str, Any], float] = {}  # (client, key) -> latest time it saw

    def _set(self, key: Any, value: Any) -> None:
        self.data[key] = value
        h = self.history.setdefault(key, [])
        h.append((now(), value))
        if len(h) > 64:
            del h[:-64]

    async def on_read(self, msg: Message) -> None:
        key = msg.body.get("key")
        if key not in self.data:
            self.reply(msg, {"type": "error", "code": 20, "text": "key does not exist"})
            return
        value = self.data[key]
        if self.stale > 0:  # seq-kv: maybe an older value, but never older than this client saw
            floor = self._seen.get((msg.src, key), 0.0)
            cutoff = max(now() - self.stale * self.rng.random(), floor)
            history = self.history.get(key, [])
            t, value = next(((t, v) for t, v in reversed(history) if t <= cutoff), history[0])
            self._seen[(msg.src, key)] = max(floor, t)
        self.reply(msg, {"type": "read_ok", "value": value})

    async def on_write(self, msg: Message) -> None:
        self._set(msg.body.get("key"), msg.body.get("value"))
        self._seen[(msg.src, msg.body.get("key"))] = now()
        self.reply(msg, {"type": "write_ok"})

    async def on_cas(self, msg: Message) -> None:
        key, frm, to = msg.body.get("key"), msg.body.get("from"), msg.body.get("to")
        if key not in self.data:
            if msg.body.get("create_if_not_exists"):
                self._set(key, to)
                self.reply(msg, {"type": "cas_ok"})
            else:
                self.reply(msg, {"type": "error", "code": 20, "text": "key does not exist"})
            return
        if self.data[key] != frm:
            self.reply(msg, {"type": "error", "code": 22,
                             "text": f"expected {frm!r}, found {self.data[key]!r}"})
            return
        self._set(key, to)
        self._seen[(msg.src, key)] = now()
        self.reply(msg, {"type": "cas_ok"})


class KV:
    """A client for a KV service, used from inside a node: `kv = KV(self, "seq-kv")`."""

    def __init__(self, node: Endpoint, service: str = "seq-kv", timeout: float = 1.0) -> None:
        self.node, self.service, self.timeout = node, service, timeout

    async def read(self, key: Any) -> Any:
        return (await self.node.rpc(self.service, {"type": "read", "key": key}, self.timeout))["value"]

    async def write(self, key: Any, value: Any) -> None:
        await self.node.rpc(self.service, {"type": "write", "key": key, "value": value}, self.timeout)

    async def cas(self, key: Any, frm: Any, to: Any, create: bool = False) -> None:
        await self.node.rpc(self.service, {"type": "cas", "key": key, "from": frm, "to": to,
                                           "create_if_not_exists": create}, self.timeout)


class Client(Endpoint):
    """A workload client: it sends requests to server nodes and waits for replies."""


def ask(node: Node, body: Body) -> Body | None:
    """Call a node's handler directly, outside the network, and return its reply (or None).

    The checker uses this to look at what a node knows without sending messages
    (so it does not count as traffic). The handler must reply synchronously, i.e.
    without awaiting anything; most `on_read` handlers do.
    """
    captured: list[Body] = []
    msg = Message("checker", node.node_id, {**body, "msg_id": -1})
    original = node.send

    def capture(dest: str, b: Body) -> None:
        if dest == "checker":
            captured.append(b)
        else:
            original(dest, b)

    handler = getattr(node, f"on_{body.get('type', '')}", None)
    if handler is None:
        return None
    node.send = capture  # type: ignore[method-assign]
    try:
        coro = handler(msg)
        try:
            coro.send(None)  # run it until it finishes or awaits something
        except StopIteration:
            pass
        else:
            coro.close()  # it wanted to wait: not a plain read
    finally:
        del node.send
    return captured[0] if captured else None


@dataclass(slots=True)
class Topology:
    """Neighbours on a grid, like Maelstrom's default topology."""

    neighbours: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def grid(cls, ids: list[str]) -> "Topology":
        side = max(1, round(len(ids) ** 0.5))
        out: dict[str, list[str]] = {}
        for i, n in enumerate(ids):
            r, c = divmod(i, side)
            near = []
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                j = rr * side + cc
                if 0 <= rr and 0 <= cc < side and j < len(ids):
                    near.append(ids[j])
            out[n] = near
        return cls(out)
