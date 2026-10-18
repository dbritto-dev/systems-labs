"""Lab kafka_style_log: YOUR FILE. Edit it and save; the live window reruns it.

This is Fly.io's Gossip Glomers challenge #5 (https://fly.io/dist-sys/5a/), in Python.
A Kafka-style log: each key ("k0" ... "k9") is a log of messages, and each message gets an
integer offset. Two nodes serve clients, who talk to either node:

  send {key, msg}                       -> send_ok {offset}
  poll {offsets: {key: from}}           -> poll_ok {msgs: {key: [[offset, msg], ...]}}
  commit_offsets {offsets: {key: off}}  -> commit_offsets_ok
  list_committed_offsets {keys: [...]}  -> list_committed_offsets_ok {offsets: {key: off}}

The rules (the checker watches every reply):
  - offsets for a key are unique and always increase: two messages never share one, a send
    never gets an offset below one already acknowledged, and a poll lists them in order;
  - no lost writes: a poll may return any number of messages from `from` on, but never
    skip an offset that was already acknowledged (or return a different message at it);
  - committed offsets never go back: listing returns at least the latest acknowledged commit.

Right now the node handles none of these, so every request gets an error.

Do the stages in order, in this file:

  Stage 1  Single node (5a): handle the four requests, each node keeping its own log in
           memory: a list of messages per key (the offset is the index) and the committed
           offset per key. Correct with one node, wrong with two (both hand out offset 0).
  Stage 2  Multi-node (5b): make both nodes agree. Maelstrom's two stores are there:
           `lin-kv` (linearizable) and `seq-kv` (sequentially consistent: a read may return an
           older value, here up to 0.5 s old). `kv = KV(self, "lin-kv")` or
           `KV(self, "seq-kv")`, then `await kv.read(k)`, `await kv.write(k, v)`,
           `await kv.cas(k, from_, to, create=True)` (RPCError code 20: no such key,
           22: someone changed it first). E.g. a counter per key for offsets (CAS until it
           sticks), and every message stored so any node can serve polls.
           Fly.io asks you to choose which data needs lin-kv. Here a message stored once under
           its own key never changes, so a stale read cannot show an older one, and a CAS
           counter is checked against the latest value (a stale read only costs a retry): both
           can live in seq-kv. Committed offsets cannot: the other node may read an older
           commit, and a listed commit that goes back is a lost commit. Keep those in lin-kv.
  Stage 3  Efficient (5c): far fewer messages per operation, and fast even when one key
           gets hammered or the store is slow (many CAS retries on one counter hurt).

How your node talks (see core/net.py):
  self.node_id, self.node_ids         who you are ("n0" or "n1"), and both nodes
  self.reply(msg, {...})              answer a request
  await self.rpc(dest, {...}, timeout=0.5)   ask another node (or a store) and wait

Check yourself:  uv run pytest labs/kafka_style_log
Peek at a solution (after trying!):  labs/kafka_style_log/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class KafkaNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)

    # Stage 1: keep, in __init__,
    #     self.logs: dict[str, list[int]] = {}   # key -> messages; the offset is the index
    #     self.commits: dict[str, int] = {}      # key -> committed offset
    # and add
    #     async def on_send(self, msg: Message) -> None:
    #         append msg.body["msg"] to the key's log, reply {"type": "send_ok", "offset": ...}
    #     async def on_poll(self, msg: Message) -> None:
    #         for each key and `from` in msg.body["offsets"], up to a few [offset, msg] pairs
    #         from there on: {"type": "poll_ok", "msgs": {key: [[offset, msg], ...]}}
    #     async def on_commit_offsets(self, msg: Message) -> None:
    #         keep the highest offset per key, reply {"type": "commit_offsets_ok"}
    #     async def on_list_committed_offsets(self, msg: Message) -> None:
    #         reply {"type": "list_committed_offsets_ok", "offsets": {key: offset}} for the
    #         keys in msg.body["keys"] that have a commit
    #
    # Stage 2: keep offsets, messages and commits in the stores (from core.net import KV,
    # RPCError), so either node can answer any request.
    #
    # Stage 3: count the round trips on a send. Could one node own each key?
