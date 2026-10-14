"""Lab kafka_style_log: YOUR FILE. Edit it and save; the live window reruns it.

This is Fly.io's Gossip Glomers challenge #5 (https://fly.io/dist-sys/5a/), in Python.
A Kafka-style log: each key ("k0" ... "k9") is a log of messages, and each message gets an
integer offset. Two nodes serve clients, who talk to either node:

  send {key, msg}                       -> send_ok {offset}
  poll {offsets: {key: from}}           -> poll_ok {msgs: {key: [[offset, msg], ...]}}
  commit_offsets {offsets: {key: off}}  -> commit_offsets_ok
  list_committed_offsets {keys: [...]}  -> list_committed_offsets_ok {offsets: {key: off}}

The rules (the checker watches every reply):
  - offsets for a key are unique: two messages never share one;
  - no lost writes: a poll may return any number of messages from `from` on, but never
    skip an offset that was already acknowledged (or return a different message at it);
  - committed offsets never go back: listing returns at least the latest acknowledged commit.

Right now each node keeps its own log: correct with one node (challenge 5a), wrong with two.

Do the stages in order, in this file:

  Stage 1  Multi-node (5b): make both nodes agree. Maelstrom's `lin-kv` (linearizable) is
           there: `kv = KV(self, "lin-kv")`, `await kv.read(k)`, `await kv.write(k, v)`,
           `await kv.cas(k, from_, to, create=True)` (RPCError code 20: no such key,
           22: someone changed it first). E.g. a counter per key for offsets (CAS until it
           sticks), and every message stored so any node can serve polls.
  Stage 2  Efficient (5c): far fewer messages per operation, and fast even when one key
           gets hammered or lin-kv is slow (many CAS retries on one counter hurt).

How your node talks (see core/net.py):
  self.node_id, self.node_ids         who you are ("n0" or "n1"), and both nodes
  self.reply(msg, {...})              answer a request
  await self.rpc(dest, {...}, timeout=0.5)   ask another node (or "lin-kv") and wait

Check yourself:  uv run pytest labs/kafka_style_log
Peek at a solution (after trying!):  labs/kafka_style_log/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class KafkaNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.logs: dict[str, list[int]] = {}  # key -> messages; the offset is the index
        self.commits: dict[str, int] = {}

    async def on_send(self, msg: Message) -> None:
        log = self.logs.setdefault(msg.body["key"], [])
        log.append(msg.body["msg"])
        self.reply(msg, {"type": "send_ok", "offset": len(log) - 1})

    async def on_poll(self, msg: Message) -> None:
        out = {}
        for key, start in msg.body["offsets"].items():
            log = self.logs.get(key, [])
            out[key] = [[i, log[i]] for i in range(start, min(len(log), start + 10))]
        self.reply(msg, {"type": "poll_ok", "msgs": out})

    async def on_commit_offsets(self, msg: Message) -> None:
        for key, offset in msg.body["offsets"].items():
            self.commits[key] = max(offset, self.commits.get(key, -1))
        self.reply(msg, {"type": "commit_offsets_ok"})

    async def on_list_committed_offsets(self, msg: Message) -> None:
        offsets = {k: self.commits[k] for k in msg.body["keys"] if k in self.commits}
        self.reply(msg, {"type": "list_committed_offsets_ok", "offsets": offsets})
