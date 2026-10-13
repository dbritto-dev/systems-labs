"""Lab txn: a working solution (stage 3, read committed). Read it after you have tried main.py.

Every transaction gets a stamp (time, node rank, counter): a total order every node agrees on.
A node runs the transaction on its own store in one go (it never awaits inside on_txn),
answers, and queues the transaction's *final* value for each key it wrote, with the stamp,
for every other node. Every 100 ms it sends each node one batch of what that node has not
acknowledged yet. A node applies a batch in one go, key by key keeping the larger stamp
(last writer wins), and acknowledges it.

- Read uncommitted (G0): every node orders the writes of a key by the same stamps.
- Read committed (G1b): only final values leave a node, and a batch is applied at once, so
  no one ever sees a value a transaction overwrote itself.
- Totally available: a node never waits for another to answer a client; a partition only
  delays replication, and the batches go again until acknowledged.
"""

from __future__ import annotations

import itertools

from core.net import Message, Node

BATCH = 0.1  # send unacknowledged transactions this often
TIMEOUT = 0.5


class TxnNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[int, int] = {}
        self.stamps: dict[int, tuple] = {}  # key -> the stamp of its current value
        self.rank = node_ids.index(node_id)
        self.counter = itertools.count()
        self.outbox: dict[str, dict[tuple, list]] = {n: {} for n in node_ids if n != node_id}
        self.every(BATCH, self.flush)

    def apply(self, stamp: tuple, writes: list) -> None:
        for key, value in writes:
            if stamp > self.stamps.get(key, ()):
                self.store[key] = value
                self.stamps[key] = stamp

    async def on_txn(self, msg: Message) -> None:
        stamp = (self.now(), self.rank, next(self.counter))
        result, final = [], {}
        for op, key, value in msg.body["txn"]:
            if op == "r":
                result.append(["r", key, self.store.get(key)])
            else:
                self.store[key] = value
                self.stamps[key] = stamp
                final[key] = value
                result.append(["w", key, value])
        self.reply(msg, {"type": "txn_ok", "txn": result})
        if final:
            for box in self.outbox.values():
                box[stamp] = list(final.items())

    async def flush(self) -> None:
        for dest, box in self.outbox.items():
            if box:
                self.spawn(self.send_batch(dest, dict(box)))

    async def send_batch(self, dest: str, batch: dict[tuple, list]) -> None:
        txns = [[list(stamp), writes] for stamp, writes in batch.items()]
        await self.rpc(dest, {"type": "replicate", "txns": txns}, timeout=TIMEOUT)
        for stamp in batch:  # acknowledged
            self.outbox[dest].pop(stamp, None)

    async def on_replicate(self, msg: Message) -> None:
        for stamp, writes in sorted(msg.body["txns"]):
            self.apply(tuple(stamp), writes)
        self.reply(msg, {"type": "replicate_ok"})
