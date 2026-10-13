"""Lab g_counter: a working solution (stage 3). Read it after you have tried main.py.

Each node owns one seq-kv key, `count-<node id>`, and is the only one that ever writes it.
So there is nothing to fight over: no compare-and-swap, no retries. The node keeps its own
total in memory and writes it out in batches, one write at a time (so writes never arrive
out of order), and acknowledges an add once a write that includes it has succeeded.

A read adds up every node's key. Your own key is always fresh (seq-kv shows you your own
writes); the others may be up to a second old, which this challenge allows: the counter only
has to be eventually right.
"""

from __future__ import annotations

import asyncio

from core.net import KV, Message, Node, RPCError

FLUSH = 0.05  # seconds between writes of our total


class CounterNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.kv = KV(self, "seq-kv")
        self.mine = 0  # everything added through this node
        self.written = 0  # what seq-kv has for our key
        self.waiting: list[tuple[int, Message]] = []  # (total that includes it, request)
        self.writing = False  # one write at a time, so they never arrive out of order
        self.every(FLUSH, self.flush)

    @staticmethod
    def key(node_id: str) -> str:
        return f"count-{node_id}"

    async def on_add(self, msg: Message) -> None:
        self.mine += msg.body["delta"]
        self.waiting.append((self.mine, msg))

    async def flush(self) -> None:
        if self.mine != self.written and not self.writing:
            self.writing = True
            self.spawn(self.write(self.mine))

    async def write(self, total: int) -> None:
        try:
            await self.kv.write(self.key(self.node_id), total)
        finally:
            self.writing = False  # done, or timed out: the next flush tries again
        self.written = total
        done = [m for t, m in self.waiting if t <= total]
        self.waiting = [(t, m) for t, m in self.waiting if t > total]
        for m in done:
            self.reply(m, {"type": "add_ok"})

    async def read_key(self, node_id: str) -> int:
        try:
            return await self.kv.read(self.key(node_id))
        except RPCError as e:
            if e.code == 20:  # that node has not counted anything yet
                return 0
            raise

    async def on_read(self, msg: Message) -> None:
        values = await asyncio.gather(*(self.read_key(n) for n in self.node_ids))
        self.reply(msg, {"type": "read_ok", "value": sum(values)})
