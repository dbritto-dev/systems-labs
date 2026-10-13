"""Lab unique_ids: a working solution (stage 3). Read it after you have tried main.py.

Snowflake ids, like Twitter's: one 63-bit integer made of

    milliseconds since a custom epoch (41 bits) | node number (10 bits) | sequence (12 bits)

Unique without asking anyone: the node number makes two nodes' ids differ, and the
sequence makes ids from the same node in the same millisecond differ. Ordered by time
because the milliseconds come first.

The clock can jump back (NTP, a VM pause). Then we keep using the last timestamp we
used and keep counting the sequence (borrowing the next millisecond when it runs out),
so ids never repeat and never go backwards.
"""

from __future__ import annotations

from core.net import Message, Node

EPOCH_MS = 1_735_689_600_000  # 2025-01-01: 41 bits of milliseconds last ~69 years from here
NODE_BITS, SEQ_BITS = 10, 12
MAX_SEQ = (1 << SEQ_BITS) - 1


class UniqueIdNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.number = int(node_id.removeprefix("n"))
        self.last_ms = -1
        self.seq = 0

    async def on_echo(self, msg: Message) -> None:
        self.reply(msg, {"type": "echo_ok", "echo": msg.body["echo"]})

    async def on_generate(self, msg: Message) -> None:
        self.reply(msg, {"type": "generate_ok", "id": self.next_id()})

    def next_id(self) -> int:
        ms = max(self.wall_ms() - EPOCH_MS, self.last_ms)  # never step back with the clock
        if ms == self.last_ms:
            self.seq += 1
            if self.seq > MAX_SEQ:  # used up this millisecond: borrow the next one
                ms, self.seq = ms + 1, 0
        else:
            self.seq = 0
        self.last_ms = ms
        return (ms << (NODE_BITS + SEQ_BITS)) | (self.number << SEQ_BITS) | self.seq
