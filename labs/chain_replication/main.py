"""Lab chain_replication: YOUR FILE. Edit it and save; the live window reruns it.

A key/value store kept on 4 nodes (n0..n3) on a network where every message takes ~30 ms. A
configuration master (reliable, like ZooKeeper or etcd) holds the order of the nodes, head first,
and sends every node the new order when it changes (`self.chain`). Clients write (`put`) to the
head, `self.chain[0]`, and read (`get`) from the node `read_from(chain, rng)` picks.

Right now it is primary-backup with asynchronous replication: the head (the primary) applies a
write, answers at once, and ships its new writes to the backups every half second. Reads spread
over every replica, so they often miss a write that was already acknowledged (stale reads); and
when the primary crashes, the writes it acknowledged but had not shipped are gone.

Do the stages in order, in this file:

  Stage 1  A chain. The head numbers every write (`seq`) and passes it to its successor; every
           node applies the writes in order and passes them on; the tail applies it last and
           answers the client, and sends an `ack` back up the chain, so every node forgets what it
           was keeping. Read from the tail: it only has writes that every replica has. No stale
           reads, no lost writes; but kill a node and the chain stalls.
  Stage 2  Repair. In `chain_changed` (the master changed the chain):
           - you are the new head: drop the writes you were holding for a gap;
           - you are the new tail: answer the writes you sent and never saw acknowledged;
           - you have a new successor: resend it every write you sent and never saw acknowledged.
           A node that comes back joins at the tail after copying the tail's state (given,
           `on_join`): the tail must keep what it applies after the copy, to resend it.

The messages (the master and the clients send theirs; you send the rest):
  put {key, value}     -> the tail answers it: self.answer(write)       (client -> head)
  get {key}            -> get_ok {value}                                 (client -> read_from)
  write {seq, key, value, client, req}                                   (down the chain)
  ack {seq}            "every write up to seq is on the tail"            (up the chain)
  config {chain}, join {tail}, snapshot -> snapshot_ok {store, seq}      (given)

How your node talks (see core/net.py):
  self.node_id, self.chain          who you are, and the chain (head first)
  self.predecessor(), self.successor()   your neighbours (None at the ends)
  self.send(dest, {...})            fire and forget
  self.reply(msg, {...})            answer a request
  self.every(seconds, coroutine_function), self.spawn(coroutine), self.now()

Keep the data in `self.store`, as {key: value}: the checker looks there.

Check yourself:  uv run pytest labs/chain_replication
Peek at a solution (after trying!):  labs/chain_replication/reference.py
"""

from __future__ import annotations

import random

from core.net import Message, Node

SHIP = 0.5  # stage 0: the primary ships its new writes to the backups this often
SNAPSHOT_TIMEOUT = 3.0  # a joining node waits this long for the tail's copy


def read_from(chain: list[str], rng: random.Random) -> str:
    """Which node a client reads from (chain: head first, tail last).

    Stage 0 (given): any replica, to spread the load. Stage 1: the tail.
    """
    return rng.choice(chain)


class ChainNode(Node):
    """One replica.

    Contract:
      - a write reaches every node in the chain, in the same order, before its client is answered;
      - `get` answers from `self.store`; `self.store[key] = value` is what this node holds;
      - `chain_changed(old)` runs every time the master sends a new chain.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.chain: list[str] = []  # the master says: head first, tail last
        self.store: dict[str, int] = {}  # key -> value (the checker looks here)
        self.seq = 0  # the last write applied here
        self.pending: dict[int, dict] = {}  # writes that arrived ahead of a gap: seq -> write
        self.sent: dict[int, dict] = {}  # passed down, not yet acknowledged by the tail: seq -> write
        self.copying = False  # as the tail: a node is copying our state (stage 2)
        self.backlog: list[tuple] = []  # stage 0: writes the primary has not shipped yet
        self.every(SHIP, self.ship)

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
        """Copy the tail's state; the master adds this node as the new tail once it answers."""
        snap = await self.rpc(msg.body["tail"], {"type": "snapshot"}, timeout=SNAPSHOT_TIMEOUT)
        self.store, self.seq = dict(snap["store"]), snap["seq"]
        self.pending.clear()
        self.reply(msg, {"type": "join_ok"})

    async def on_snapshot(self, msg: Message) -> None:
        # Stage 2: set self.copying = True. A node is copying you; when the master makes it your
        # successor it needs every write you applied after this copy: `apply` keeps them in self.sent.
        self.reply(msg, {"type": "snapshot_ok", "store": dict(self.store), "seq": self.seq})

    # ---- clients

    async def on_get(self, msg: Message) -> None:
        self.reply(msg, {"type": "get_ok", "value": self.store.get(msg.body["key"])})

    async def on_put(self, msg: Message) -> None:
        """A client's write, at the head."""
        # Stage 1: replace all of this with
        #     self.apply({"seq": self.seq + 1, "key": ..., "value": ..., "client": msg.src,
        #                 "req": msg.body["msg_id"]})
        # (the client's address and request id travel with the write: the tail answers it).
        key, value = msg.body["key"], msg.body["value"]
        self.seq += 1
        self.store[key] = value
        self.backlog.append((self.seq, key, value))
        self.reply(msg, {"type": "put_ok"})  # acknowledged before any backup has it

    async def ship(self) -> None:
        """Stage 0 (given): the primary ships its new writes to the backups."""
        if self.backlog and self.predecessor() is None:
            items, self.backlog = self.backlog, []
            for backup in self.chain[1:]:
                self.send(backup, {"type": "replicate", "items": items})

    async def on_replicate(self, msg: Message) -> None:
        """Stage 0 (given): a backup applies what the primary shipped."""
        for seq, key, value in msg.body["items"]:
            if seq > self.seq:
                self.seq = seq
                self.store[key] = value

    # ---- the chain

    async def on_write(self, msg: Message) -> None:
        """Stage 1. A write from your predecessor: {"seq", "key", "value", "client", "req"}.

        Messages can overtake each other, and a write must be applied in seq order: keep it in
        self.pending[seq], then apply (self.apply) while self.seq + 1 is in self.pending.
        Ignore a write whose seq is <= self.seq: you have it already (stage 2 resends some).
        """
        raise NotImplementedError("TODO stage 1: ChainNode.on_write")

    def apply(self, write: dict) -> None:
        """Stage 1. Apply one write (it is the next in order) and pass it on.

        self.store[key] = value and self.seq = seq. Then:
          - with a successor: keep it in self.sent[seq] and send it {"type": "write", **write};
          - at the tail: answer the client (self.answer(write)) and send {"type": "ack", "seq": seq}
            to your predecessor, if you have one.
        Stage 2: at the tail, while self.copying, keep it in self.sent[seq] too.
        """
        raise NotImplementedError("TODO stage 1: ChainNode.apply")

    async def on_ack(self, msg: Message) -> None:
        """Stage 1. Every write up to msg.body["seq"] is on the tail: drop them from self.sent and
        pass the ack to your predecessor, if you have one."""
        raise NotImplementedError("TODO stage 1: ChainNode.on_ack")

    # ---- repair

    async def chain_changed(self, old: list[str]) -> None:
        """Stage 2. The master changed the chain: `old` was it before, `self.chain` is it now.

        Find your old neighbours in `old` (none if you were not in it) and compare them with
        self.predecessor() and self.successor():
          - no predecessor now, one before: you are the head. self.pending.clear(): the old head
            died, the gap you were waiting for will never come.
          - no successor now, one before: you are the tail. Answer every write in self.sent
            (in seq order), clear it, and ack self.seq to your predecessor.
          - a successor now, and a different one: resend it every write in self.sent, in seq
            order (it ignores the ones it has). Then self.copying = False.
        """
        return
