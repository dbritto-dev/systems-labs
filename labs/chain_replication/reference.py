"""Lab chain_replication: a working solution (stage 2). Read it after you have tried main.py.

A chain: the head numbers every write and passes it down; each node applies the writes in order and
passes them on; the tail applies it last and answers the client, and its acknowledgement climbs back
up the chain so every node can forget it. Reads go to the tail: it only holds writes every replica
has, so a read never sees a value that could still be lost, and never misses an acknowledged one.

Repair, when the master changes the chain:
  - the head died: the next node is the head. Writes waiting for a gap from the old head never come.
  - the tail died: its predecessor is the tail. It answers the writes it sent and never saw acked.
  - a middle node died: its predecessor resends what it sent and never saw acked to its new successor
    (the successor drops what it already has).
  - a node joins: it copies the tail's state; the tail keeps what it applies after the copy and
    resends it once the node is its successor (the same resend as a middle repair).
"""

from __future__ import annotations

import random

from core.net import Message, Node

SHIP = 0.5  # stage 0: the primary ships its new writes to the backups this often
SNAPSHOT_TIMEOUT = 3.0  # a joining node waits this long for the tail's copy


def read_from(chain: list[str], rng: random.Random) -> str:
    """Which node a client reads from: the tail, the only one that holds nothing unacknowledged."""
    return chain[-1]


class ChainNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.chain: list[str] = []  # the master says: head first, tail last
        self.store: dict[str, int] = {}  # key -> value (the checker looks here)
        self.seq = 0  # the last write applied here
        self.pending: dict[int, dict] = {}  # writes that arrived ahead of a gap: seq -> write
        self.sent: dict[int, dict] = {}  # passed down, not yet acknowledged by the tail: seq -> write
        self.copying = False  # as the tail: a node is copying our state, keep what we apply in sent

    # ---- where we are in the chain (given)

    def predecessor(self) -> str | None:
        if self.node_id not in self.chain:
            return None
        i = self.chain.index(self.node_id)
        return self.chain[i - 1] if i > 0 else None

    def successor(self) -> str | None:
        if self.node_id not in self.chain:
            return None
        i = self.chain.index(self.node_id)
        return self.chain[i + 1] if i + 1 < len(self.chain) else None

    def answer(self, write: dict) -> None:
        """Tell the client its write is done (given). A client ignores a second answer."""
        self.send(write["client"], {"type": "put_ok", "in_reply_to": write["req"]})

    # ---- the master (given)

    async def on_config(self, msg: Message) -> None:
        old, self.chain = self.chain, list(msg.body["chain"])
        await self.chain_changed(old)
        self.reply(msg, {"type": "config_ok"})

    async def on_join(self, msg: Message) -> None:
        snap = await self.rpc(msg.body["tail"], {"type": "snapshot"}, timeout=SNAPSHOT_TIMEOUT)
        self.store, self.seq = dict(snap["store"]), snap["seq"]
        self.pending.clear()
        self.reply(msg, {"type": "join_ok"})

    async def on_snapshot(self, msg: Message) -> None:
        self.copying = True  # what we apply from now on, the new node will need
        self.reply(msg, {"type": "snapshot_ok", "store": dict(self.store), "seq": self.seq})

    # ---- clients

    async def on_get(self, msg: Message) -> None:
        self.reply(msg, {"type": "get_ok", "value": self.store.get(msg.body["key"])})

    async def on_put(self, msg: Message) -> None:
        """At the head: number the write and start it down the chain."""
        self.apply({"seq": self.seq + 1, "key": msg.body["key"], "value": msg.body["value"],
                    "client": msg.src, "req": msg.body["msg_id"]})

    # ---- the chain

    async def on_write(self, msg: Message) -> None:
        write = {k: msg.body[k] for k in ("seq", "key", "value", "client", "req")}
        if write["seq"] <= self.seq:
            return  # a resend of something we already have
        self.pending[write["seq"]] = write
        while self.seq + 1 in self.pending:
            self.apply(self.pending.pop(self.seq + 1))

    def apply(self, write: dict) -> None:
        self.store[write["key"]] = write["value"]
        self.seq = write["seq"]
        succ = self.successor()
        if succ is None:  # the tail: done
            self.answer(write)
            if self.copying:
                self.sent[write["seq"]] = write
            pred = self.predecessor()
            if pred is not None:
                self.send(pred, {"type": "ack", "seq": write["seq"]})
        else:
            self.sent[write["seq"]] = write
            self.send(succ, {"type": "write", **write})

    async def on_ack(self, msg: Message) -> None:
        seq = msg.body["seq"]
        for s in [s for s in self.sent if s <= seq]:
            del self.sent[s]
        pred = self.predecessor()
        if pred is not None:
            self.send(pred, {"type": "ack", "seq": seq})

    # ---- repair

    async def chain_changed(self, old: list[str]) -> None:
        if self.node_id not in self.chain:
            return
        mine = old.index(self.node_id) if self.node_id in old else None
        old_pred = old[mine - 1] if mine is not None and mine > 0 else None
        old_succ = old[mine + 1] if mine is not None and mine + 1 < len(old) else None
        pred, succ = self.predecessor(), self.successor()
        if pred is None and old_pred is not None:  # we are the head now
            self.pending.clear()  # the old head will never fill the gap
        if succ is None and old_succ is not None:  # we are the tail now
            for seq in sorted(self.sent):
                self.answer(self.sent[seq])
            self.sent.clear()
            if pred is not None:
                self.send(pred, {"type": "ack", "seq": self.seq})
        elif succ is not None and succ != old_succ:  # a new successor: resend what it may lack
            for seq in sorted(self.sent):
                self.send(succ, {"type": "write", **self.sent[seq]})
            self.copying = False
