"""Lab quorum: a working solution (stage 2). Read it after you have tried main.py.

Quorums: a write goes to the key's N=3 replicas and is acknowledged after W=2 of them; a read
asks the replicas and answers from the newest of R=2 replies. W + R > N, so a read always
overlaps the last acknowledged write, and one sick node changes nothing for the clients.

Repair: every write a replica missed becomes a hint, re-sent (in one batch per replica) every
half a second until that replica acknowledges it (hinted handoff); and a read that sees a
stale replica sends it the newest version (read repair).
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError

N, W, R = 3, 2, 2
TIMEOUT = 0.5  # wait this long for a replica
HAND_OFF = 0.5  # re-send hints this often
LOWEST = (-1.0, "")  # the version of a key a replica does not have


def replicas_for(key: str, node_ids: list[str], n: int = N) -> list[str]:
    """The n nodes that hold `key`: its home node and the next ones round the ring. (Given: do not change.)"""
    home = int(key[1:]) % len(node_ids)
    return [node_ids[(home + j) % len(node_ids)] for j in range(n)]


class QuorumNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple] = {}
        self.hints: dict[str, dict[str, tuple]] = {}  # replica -> {key: (version, value)}
        self.every(HAND_OFF, self.hand_off)

    # ---- as a replica

    def keep(self, key: str, version, value) -> None:
        """Keep the newer of what we have and what we got."""
        version = tuple(version)
        old = self.store.get(key)
        if old is None or version > tuple(old[0]):
            self.store[key] = (version, value)

    async def on_store(self, msg: Message) -> None:
        self.keep(msg.body["key"], msg.body["version"], msg.body["value"])
        self.reply(msg, {"type": "store_ok"})

    async def on_store_many(self, msg: Message) -> None:
        for key, version, value in msg.body["items"]:
            self.keep(key, version, value)
        self.reply(msg, {"type": "store_many_ok"})

    async def on_fetch(self, msg: Message) -> None:
        entry = self.store.get(msg.body["key"])
        version, value = entry if entry else (LOWEST, None)
        self.reply(msg, {"type": "fetch_ok", "version": version, "value": value})

    # ---- as the coordinator

    async def replicate(self, replica: str, key: str, version, value) -> bool:
        body = {"type": "store", "key": key, "version": version, "value": value}
        try:
            await self.rpc(replica, body, timeout=TIMEOUT)
            return True
        except (TimeoutError, RPCError):
            hints = self.hints.setdefault(replica, {})
            if key not in hints or tuple(version) > tuple(hints[key][0]):
                hints[key] = (version, value)  # hand it over later
            return False

    async def on_put(self, msg: Message) -> None:
        key, value = msg.body["key"], msg.body["value"]
        version = (self.now(), self.node_id)
        tasks = [asyncio.ensure_future(self.replicate(r, key, version, value))
                 for r in replicas_for(key, self.node_ids)]
        acks = 0
        for done in asyncio.as_completed(tasks):
            acks += await done
            if acks >= W:
                self.reply(msg, {"type": "put_ok"})
                return
        self.reply(msg, {"type": "error", "code": 11, "text": "not enough replicas"})

    async def fetch(self, replica: str, key: str):
        try:
            reply = await self.rpc(replica, {"type": "fetch", "key": key}, timeout=TIMEOUT)
            return replica, tuple(reply["version"]), reply["value"]
        except (TimeoutError, RPCError):
            return None

    async def on_get(self, msg: Message) -> None:
        key = msg.body["key"]
        tasks = [asyncio.ensure_future(self.fetch(r, key)) for r in replicas_for(key, self.node_ids)]
        replies = []
        for done in asyncio.as_completed(tasks):
            reply = await done
            if reply is not None:
                replies.append(reply)
            if len(replies) >= R:
                break
        if len(replies) < R:
            self.reply(msg, {"type": "error", "code": 11, "text": "not enough replicas"})
            return
        _, version, value = max(replies, key=lambda r: r[1])
        self.reply(msg, {"type": "get_ok", "value": value})
        self.spawn(self.read_repair(key, tasks, version, value))

    async def read_repair(self, key: str, tasks, version, value) -> None:
        """Once every replica answered (or timed out), send the newest version to the stale ones."""
        for reply in await asyncio.gather(*tasks):
            if reply is not None and reply[1] < version:
                self.send(reply[0], {"type": "store", "key": key, "version": version, "value": value})

    async def hand_off(self) -> None:
        for replica, items in list(self.hints.items()):
            if items:
                self.spawn(self.hand_over(replica, dict(items)))

    async def hand_over(self, replica: str, items: dict) -> None:
        body = {"type": "store_many", "items": [(k, v, x) for k, (v, x) in items.items()]}
        try:
            await self.rpc(replica, body, timeout=TIMEOUT)
        except (TimeoutError, RPCError):
            return
        hints = self.hints.get(replica, {})
        for k, entry in items.items():
            if hints.get(k) == entry:  # not replaced by a newer hint meanwhile
                del hints[k]
