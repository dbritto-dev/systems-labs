"""Lab unique_ids: YOUR FILE. Edit it and save; the live window reruns it.

Fly.io's Gossip Glomers challenges #1 and #2 (https://fly.io/dist-sys/1/ and /2/), in
Python. 5 nodes, ~100 ms per message. Clients send each node `echo` and `generate`
requests. Right now the node handles neither, so every request gets an error.

Do the stages in order, in this file:

  Stage 1  Echo (#1): answer {"type": "echo", "echo": X} with {"type": "echo_ok", "echo": X}.
  Stage 2  Unique IDs (#2): answer {"type": "generate"} with {"type": "generate_ok", "id": ...},
           an id no other request ever got, from any node. It must keep working while the
           network between the nodes is partitioned (clients still reach every node), so
           asking another node is not an option.
  Stage 3  Sortable 64-bit IDs: make the id an int from 0 to 2**63 - 1 (it fits a database
           bigint) that grows with time, so sorting ids sorts by creation (Snowflake:
           milliseconds | node | sequence). Careful: clocks can jump BACKWARDS.

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are ("n0" ... "n4"), and every node
  self.reply(msg, {...})           answer a request
  await self.rpc(dest, {...})      ask another node and wait (fails during a partition)
  self.wall_ms()                   this node's wall clock, in milliseconds since 1970
                                   (it can jump back when NTP corrects it)

Check yourself:  uv run pytest labs/unique_ids
Peek at a solution (after trying!):  labs/unique_ids/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class UniqueIdNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)

    # Stage 1: add
    #     async def on_echo(self, msg: Message) -> None:
    #         self.reply(msg, {"type": "echo_ok", "echo": msg.body["echo"]})
    #
    # Stage 2: add `async def on_generate(self, msg: Message)` that replies
    #     {"type": "generate_ok", "id": <unique>}
    # Hint: what is unique about this node, and about this request on this node?
    #
    # Stage 3: build the id from self.wall_ms(), the node number and a sequence,
    # and never let the timestamp you use go backwards.


