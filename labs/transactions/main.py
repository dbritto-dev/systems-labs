"""Lab transactions: YOUR FILE. Edit it and save; the live window reruns it.

This is Fly.io's Gossip Glomers challenge #6 (https://fly.io/dist-sys/6a/), in Python.
3 nodes hold a key/value store; every message between them takes ~100 ms. Clients send any
node a `txn`: a list of micro-operations, ["r", key, None] to read and ["w", key, value] to
write. The node answers `txn_ok` with the same list, every read filled in. Every write
value is unique. Now and then one node is cut off from the others (a partition), but the
clients still reach it: every transaction must still be answered (total availability).

Right now each node keeps its own store (6a, a single node): writes never reach the others.

Do the stages in order, in this file:

  Stage 1  Replicate (6b): send every write to the other nodes, so they catch up.
  Stage 2  Read uncommitted, through partitions (6b): re-send what the other node has not
           acknowledged; when two writes to a key cross, the newest wins everywhere
           (stamp each transaction with (time, node) and keep the larger stamp).
  Stage 3  Read committed (6c): never let anyone see a value a transaction overwrote
           itself (an "intermediate read", G1b): replicate whole transactions, with only
           their final value per key, and apply each one in one go.

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are, and every node ("n0", "n1", "n2")
  self.reply(msg, {...})           answer a request
  self.send(dest, {...})           fire and forget
  await self.rpc(dest, {...}, timeout=0.5)   send and wait for the reply (TimeoutError if lost)
  self.every(seconds, coroutine_function), self.spawn(coroutine), self.now()

Keep the current value of every key in `self.store` (a dict): the checker looks there.
Do not `await` inside on_txn between reading and writing: a handler that never awaits
runs in one go, so nobody can see it half done.

Check yourself:  uv run pytest labs/transactions
Peek at a solution (after trying!):  labs/transactions/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class TxnNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[int, int] = {}

    async def on_txn(self, msg: Message) -> None:
        result = []
        for op, key, value in msg.body["txn"]:
            if op == "r":
                result.append(["r", key, self.store.get(key)])
            else:
                self.store[key] = value
                result.append(["w", key, value])
        self.reply(msg, {"type": "txn_ok", "txn": result})
        # Stage 1: send the writes to the other nodes (a message type of your own, e.g.
        # self.send(n, {"type": "replicate", "writes": [[key, value], ...]})), and handle
        # it in `async def on_replicate(self, msg)`.
