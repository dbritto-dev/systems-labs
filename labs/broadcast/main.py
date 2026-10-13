"""Lab broadcast: YOUR FILE. Edit it and save; the live window reruns it.

This is Fly.io's Gossip Glomers challenge #3 (https://fly.io/dist-sys/3a/), in Python.
25 nodes sit on a network where every message takes ~100 ms. Clients send each node
`broadcast` (remember this number) and `read` (which numbers do you have?). Every number
must reach every node. Right now each node only keeps the numbers sent to it.

Do the stages in order, in this file:

  Stage 1  Multi-node (3b): when a node learns a new number, tell its neighbours.
  Stage 2  Fault tolerant (3c): the network partitions now and then. Keep re-sending
           until the other node says it got it (use `await self.rpc(...)` and retry).
  Stage 3  Efficient (3d): under 30 messages per operation, median latency under
           400 ms, max under 600 ms.
  Stage 4  Batched (3e): under 20 messages per operation (median under 1 s, max under
           2 s): send many numbers in one message.

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are, and every node ("n0" ... "n24")
  self.reply(msg, {...})           answer a request
  self.send(dest, {...})           fire and forget
  await self.rpc(dest, {...}, timeout=0.5)   send and wait for the reply (TimeoutError if lost)
  self.every(seconds, coroutine_function)    run something periodically

Keep every number you know in `self.messages` (a set): the checker looks there.

Check yourself:  uv run pytest labs/broadcast
Peek at a solution (after trying!):  labs/broadcast/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class BroadcastNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.messages: set[int] = set()
        self.neighbours: list[str] = []

    async def on_topology(self, msg: Message) -> None:
        """The clients send each node its neighbours on a grid once, at the start."""
        self.neighbours = msg.body["topology"][self.node_id]
        self.reply(msg, {"type": "topology_ok"})

    async def on_broadcast(self, msg: Message) -> None:
        self.messages.add(msg.body["message"])
        self.reply(msg, {"type": "broadcast_ok"})
        # Stage 1: if the number is new, send it to your neighbours, e.g. with a
        # message of your own type: self.send(n, {"type": "gossip", "message": number}),
        # and handle it in `async def on_gossip(self, msg)`.

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "messages": sorted(self.messages)})
