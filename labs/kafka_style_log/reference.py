"""Lab kafka_style_log: a working solution (stage 2). Read it after you have tried main.py.

Every key has an owner: one of the two nodes, picked by hashing the key. The owner keeps that
key's log and its committed offset in memory and hands out offsets itself: no storage round
trips, no contention. The other node forwards requests about that key to the owner (one RPC).

So a send costs 0 messages on the owner and 2 (a request and its reply) on the other node, and
nothing ever waits on lin-kv. Hot keys and a slow lin-kv do not slow it down.
"""

from __future__ import annotations

import asyncio
import zlib

from core.net import Message, Node

TIMEOUT = 0.5


class KafkaNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.logs: dict[str, list[int]] = {}
        self.commits: dict[str, int] = {}

    def owner(self, key: str) -> str:
        return self.node_ids[zlib.crc32(key.encode()) % len(self.node_ids)]

    def split(self, keys) -> dict[str, list[str]]:
        """Keys grouped by the node that owns them."""
        out: dict[str, list[str]] = {}
        for key in keys:
            out.setdefault(self.owner(key), []).append(key)
        return out

    # ---- clients

    async def on_send(self, msg: Message) -> None:
        key = msg.body["key"]
        if self.owner(key) == self.node_id:
            offset = self.append(key, msg.body["msg"])
        else:
            reply = await self.rpc(self.owner(key), {"type": "append", "key": key, "msg": msg.body["msg"]},
                                   timeout=TIMEOUT)
            offset = reply["offset"]
        self.reply(msg, {"type": "send_ok", "offset": offset})

    async def on_poll(self, msg: Message) -> None:
        wanted = msg.body["offsets"]
        out: dict = {}

        async def ask(node: str, keys: list[str]) -> None:
            part = {k: wanted[k] for k in keys}
            if node == self.node_id:
                out.update(self.read(part))
            else:
                out.update((await self.rpc(node, {"type": "read", "offsets": part}, timeout=TIMEOUT))["msgs"])

        await asyncio.gather(*(ask(n, keys) for n, keys in self.split(wanted).items()))
        self.reply(msg, {"type": "poll_ok", "msgs": out})

    async def on_commit_offsets(self, msg: Message) -> None:
        offsets = msg.body["offsets"]

        async def tell(node: str, keys: list[str]) -> None:
            part = {k: offsets[k] for k in keys}
            if node == self.node_id:
                self.commit(part)
            else:
                await self.rpc(node, {"type": "commit", "offsets": part}, timeout=TIMEOUT)

        await asyncio.gather(*(tell(n, keys) for n, keys in self.split(offsets).items()))
        self.reply(msg, {"type": "commit_offsets_ok"})

    async def on_list_committed_offsets(self, msg: Message) -> None:
        out: dict = {}

        async def ask(node: str, keys: list[str]) -> None:
            if node == self.node_id:
                out.update(self.committed(keys))
            else:
                out.update((await self.rpc(node, {"type": "committed", "keys": keys}, timeout=TIMEOUT))["offsets"])

        await asyncio.gather(*(ask(n, keys) for n, keys in self.split(msg.body["keys"]).items()))
        self.reply(msg, {"type": "list_committed_offsets_ok", "offsets": out})

    # ---- the owner's side

    def append(self, key: str, value: int) -> int:
        log = self.logs.setdefault(key, [])
        log.append(value)
        return len(log) - 1

    def read(self, offsets: dict[str, int]) -> dict[str, list]:
        out = {}
        for key, start in offsets.items():
            log = self.logs.get(key, [])
            out[key] = [[i, log[i]] for i in range(start, min(len(log), start + 10))]
        return out

    def commit(self, offsets: dict[str, int]) -> None:
        for key, offset in offsets.items():
            self.commits[key] = max(offset, self.commits.get(key, -1))

    def committed(self, keys: list[str]) -> dict[str, int]:
        return {k: self.commits[k] for k in keys if k in self.commits}

    async def on_append(self, msg: Message) -> None:
        self.reply(msg, {"type": "append_ok", "offset": self.append(msg.body["key"], msg.body["msg"])})

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "msgs": self.read(msg.body["offsets"])})

    async def on_commit(self, msg: Message) -> None:
        self.commit(msg.body["offsets"])
        self.reply(msg, {"type": "commit_ok"})

    async def on_committed(self, msg: Message) -> None:
        self.reply(msg, {"type": "committed_ok", "offsets": self.committed(msg.body["keys"])})
