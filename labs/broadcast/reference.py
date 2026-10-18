"""Lab broadcast: a working solution (stages 4 and 5). Read it after you have tried main.py.

A hub (n0) with batches, and acknowledgements that are batched too:

- A node that gets a new number from a client sends it to the hub straight away.
- Every 50 ms the hub sends one batch, with every number new since the last batch, to every
  node (the origin too: getting its own number back tells it the hub has it).
- Once a second each node tells the hub which numbers it got (one ack message), and re-sends
  to the hub its own numbers the hub has not echoed back yet. The hub re-sends to a node
  whatever that node has not acknowledged after a second.

Fire-and-forget on the fast path keeps it quick (one hop in, up to 50 ms, one hop out:
~350 ms median); the slow path (acks and re-sends) makes it survive partitions. About 14
messages per operation at 20 operations/s.
"""

from __future__ import annotations

from core.net import Message, Node

BATCH = 0.05  # the hub sends a batch this often (only when it has something to send)
SYNC = 1.0  # acks and re-sends this often


class BroadcastNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.messages: set[int] = set()
        self.hub = node_ids[0]
        self.is_hub = node_id == self.hub
        if self.is_hub:
            self.fresh: set[int] = set()  # new since the last batch
            self.outstanding: dict[str, dict[int, float]] = {n: {} for n in node_ids if n != node_id}
            self.every(BATCH, self.send_batches)
        else:
            self.unconfirmed: dict[int, float] = {}  # my clients' numbers the hub has not echoed
            self.received: set[int] = set()  # got from the hub since my last ack
            self.every(SYNC, self.sync)

    # ---- clients

    async def on_topology(self, msg: Message) -> None:
        self.reply(msg, {"type": "topology_ok"})  # we use our own topology: a hub

    async def on_broadcast(self, msg: Message) -> None:
        number = msg.body["message"]
        self.reply(msg, {"type": "broadcast_ok"})
        if number in self.messages:
            return
        self.messages.add(number)
        if self.is_hub:
            self.fresh.add(number)
        else:
            self.unconfirmed[number] = self.now()
            self.send(self.hub, {"type": "up", "messages": [number]})

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "messages": sorted(self.messages)})

    # ---- the hub

    async def on_up(self, msg: Message) -> None:
        new = set(msg.body["messages"]) - self.messages
        self.messages |= new
        self.fresh |= new

    async def send_batches(self) -> None:
        t = self.now()
        for dest, waiting in self.outstanding.items():
            for number in self.fresh:
                waiting.setdefault(number, t)
            due = [n for n, since in waiting.items() if n in self.fresh or t - since >= SYNC]
            if due:
                for n in due:
                    waiting[n] = t
                self.send(dest, {"type": "down", "messages": due})
        self.fresh = set()

    async def on_ack(self, msg: Message) -> None:
        waiting = self.outstanding[msg.src]
        for number in msg.body["messages"]:
            waiting.pop(number, None)

    # ---- the other nodes

    async def on_down(self, msg: Message) -> None:
        numbers = msg.body["messages"]
        self.messages.update(numbers)
        self.received.update(numbers)
        for number in numbers:
            self.unconfirmed.pop(number, None)  # the hub has it

    async def sync(self) -> None:
        if self.received:
            self.send(self.hub, {"type": "ack", "messages": sorted(self.received)})
            self.received = set()
        late = [n for n, since in self.unconfirmed.items() if self.now() - since >= SYNC]
        if late:
            self.send(self.hub, {"type": "up", "messages": late})
