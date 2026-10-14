"""Lab grow_only_counter: YOUR FILE. Edit it and save; the live window reruns it.

This is Fly.io's Gossip Glomers challenge #4 (https://fly.io/dist-sys/4/), in Python.
3 nodes take `add` (a delta) and `read` (the total) from clients. The count must live in
Maelstrom's `seq-kv` service, a key/value store that is *sequentially consistent*: a read
may return a value up to a second old, though never older than what you wrote yourself.
Right now each node only counts the adds sent to it, in memory.

Do the stages in order, in this file:

  Stage 1  Shared count: keep the total in one seq-kv key. Read it, add, write it back.
  Stage 2  No lost adds: two nodes can read the same old value and overwrite each other.
           Use compare-and-swap (`cas`) and retry when it fails.
  Stage 3  No conflicts: every add on one hot key fights every other add. Give each node
           its own key that only it writes, and read the sum of all keys.

How your node talks (see core/net.py):
  self.node_id, self.node_ids        who you are, and every node ("n0", "n1", "n2")
  self.reply(msg, {...})             answer a request
  kv = KV(self, "seq-kv")            then: await kv.read(key), await kv.write(key, value),
                                     await kv.cas(key, old, new, create=True)
  RPCError: e.code == 20 means the key does not exist yet, 22 means cas found another value.

Check yourself:  uv run pytest labs/grow_only_counter
Peek at a solution (after trying!):  labs/grow_only_counter/reference.py
"""

from __future__ import annotations

from core.net import KV, Message, Node, RPCError  # noqa: F401  (KV and RPCError: for your stages)


class CounterNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.kv = KV(self, "seq-kv")
        self.count = 0  # Stage 1: the count must live in seq-kv, not here

    async def on_add(self, msg: Message) -> None:
        # Stage 1: read the key "counter" (a missing key, RPCError code 20, counts as 0),
        #          add msg.body["delta"], write it back, then reply.
        # Stage 2: instead of write, cas(key, old, new, create=True); on code 22 read again
        #          and retry. Reply only once it worked.
        # Stage 3: write only your own key (e.g. f"count-{self.node_id}"); you are its only
        #          writer, so keep your own total and write it (one write at a time).
        self.count += msg.body["delta"]
        self.reply(msg, {"type": "add_ok"})

    async def on_read(self, msg: Message) -> None:
        # Stage 1: read "counter" from seq-kv. Stage 3: read every node's key and add them up.
        self.reply(msg, {"type": "read_ok", "value": self.count})
