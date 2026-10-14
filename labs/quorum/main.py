"""Lab quorum: YOUR FILE. Edit it and save; the live window reruns it.

Leaderless replication, the way Amazon Dynamo, Cassandra and Riak do it. 5 nodes sit on a
network where every message takes ~100 ms. Every key lives on 3 of them, its replicas
(`replicas_for(key, self.node_ids)`). Clients send `put` and `get` to any healthy node, and
that node coordinates the request. Right now a node just keeps what it is sent and answers
from its own memory, so a `get` that lands on another node misses the latest write.

Do the stages in order, in this file:

  Stage 1  Quorums: on `put`, send the value with a version to the key's N=3 replicas and
           answer once W=2 acknowledged it; on `get`, ask the replicas and answer from the
           newest of R=2 replies. W + R > N, so every read overlaps the last write, and one
           node can be down without anyone noticing.
  Stage 2  Repair: a node that was down comes back with old data. Bring it up to date:
           keep a "hint" for every write a replica missed and hand it over when it is
           back (hinted handoff), and fix stale replicas you see while reading (read repair).

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are, and every node ("n0" ... "n4")
  self.reply(msg, {...})           answer a request
  self.send(dest, {...})           fire and forget
  await self.rpc(dest, {...}, timeout=0.5)   send and wait for the reply (TimeoutError if lost)
  self.every(seconds, coroutine_function)    run something periodically
  self.spawn(coroutine)            run something in the background
  self.now()                       the clock (the same on every node here: fine as a version)

Keep your data in `self.store`, as {key: (version, value)}: the checker looks there.
Clients never write the same key twice at the same time.

Check yourself:  uv run pytest labs/quorum
Peek at a solution (after trying!):  labs/quorum/reference.py
"""

from __future__ import annotations

from core.net import Message, Node

N, W, R = 3, 2, 2


def replicas_for(key: str, node_ids: list[str], n: int = N) -> list[str]:
    """The n nodes that hold `key`: its home node and the next ones round the ring. (Given: do not change.)"""
    home = int(key[1:]) % len(node_ids)
    return [node_ids[(home + j) % len(node_ids)] for j in range(n)]


class QuorumNode(Node):
    """Coordinates the client requests that land on it, and stores the keys it is a replica of.

    Contract:
      - `put` {key, value}  -> reply {"type": "put_ok"} once the write is safe;
      - `get` {key}         -> reply {"type": "get_ok", "value": value or None};
      - if you cannot reach enough replicas, reply {"type": "error", "code": 11};
      - `self.store[key] = (version, value)`: what this node holds.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple] = {}

    async def on_put(self, msg: Message) -> None:
        # Stage 1: version = (self.now(), self.node_id); send {"type": "store", ...} to every
        # replica in replicas_for(key, self.node_ids) and reply put_ok after W acks.
        # Hint: start one task per replica (self.spawn or asyncio.ensure_future) and count
        # the successes with asyncio.as_completed; a TimeoutError is a replica that missed it.
        # Stage 2: remember the writes a replica missed (a hint) and re-send them every
        # half a second until it acknowledges.
        key, value = msg.body["key"], msg.body["value"]
        self.store[key] = (self.now(), value)
        self.reply(msg, {"type": "put_ok"})

    async def on_get(self, msg: Message) -> None:
        # Stage 1: ask the replicas ({"type": "fetch", "key": key}), wait for R replies and
        # answer the value with the newest version.
        # Stage 2 (read repair): send the newest version to the replicas that answered with
        # an older one.
        entry = self.store.get(msg.body["key"])
        self.reply(msg, {"type": "get_ok", "value": entry[1] if entry else None})
