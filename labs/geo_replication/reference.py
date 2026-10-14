"""Lab geo_replication: a working solution (stage 2). Read it after you have tried main.py.

Writes in every region: a user's write is taken by the region they reach (their own, or the next
one when theirs is down) and acknowledged once a second region holds it too, the nearest one that
answers. Reads are answered from the region's own copy, unless the user's session token says they
have already written or seen something newer: then the region fetches it from the others first.
A region that missed writes (it was down, cut off, or behind a slow link) gets them later, from
hints (hinted handoff). Conflicts: the newest version of a key wins (last writer wins); only its
owner writes a key, one request at a time, so a newer version is always the later write.
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError
from labs.geo_replication.api import REGIONS, nearest

PRIMARY = "us"  # stages 0 and 1: the region that takes every write (stage 2 has none)
TIMEOUT = 0.4  # wait this long for another region
SHIP_EVERY = 0.1  # stage 1: send the primary's new writes to the replicas this often
HAND_OFF = 1.0  # stage 2: re-send writes a region missed this often
HAND_OFF_TIMEOUT = 1.0  # stage 2: a batch of hints may cross a slow link


class RegionNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple[float, int]] = {}  # key -> (version, value)
        self.log: list[tuple[str, float, int]] = []  # stage 1: written here, not shipped yet
        self.hints: dict[str, dict[str, tuple[float, int]]] = {r: {} for r in REGIONS if r != node_id}
        self.every(HAND_OFF, self.hand_off)

    # ---- given

    def keep(self, key: str, version: float, value: int) -> bool:
        """Keep the newer of what we have and what we got (last writer wins). True if it changed."""
        old = self.store.get(key)
        if old is None or version > old[0]:
            self.store[key] = (version, value)
            return True
        return False

    async def forward(self, msg: Message, region: str) -> None:
        """Send a user's request on to another region and relay its answer (error 11 if none)."""
        try:
            reply = await self.rpc(region, {k: v for k, v in msg.body.items() if k != "msg_id"}, timeout=TIMEOUT)
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11, "text": f"{region} did not answer"})
            return
        self.reply(msg, {k: v for k, v in reply.items() if k != "in_reply_to"})

    # ---- users

    async def on_read(self, msg: Message) -> None:
        key, token = msg.body["key"], msg.body.get("token", 0)
        version, value = self.store.get(key, (0, None))
        if version < token:  # this session has written or seen newer: get it first
            found = await self.fetch(key, token)
            if found is None:
                self.reply(msg, {"type": "error", "code": 11, "text": "no region has this session's version"})
                return
            version, value = found
        self.reply(msg, {"type": "read_ok", "value": value, "version": version})

    async def on_write(self, msg: Message) -> None:
        key, value = msg.body["key"], msg.body["value"]
        version = max(self.now(), msg.body.get("token", 0) + 1e-6)
        self.keep(key, version, value)
        if await self.replicate(key, version, value):
            self.reply(msg, {"type": "write_ok", "version": version})
        else:  # only this region holds it: not safe to acknowledge
            self.reply(msg, {"type": "error", "code": 11, "text": "no other region took the write"})

    # ---- stage 1: the replicas' side (stage 2 keeps it)

    async def ship(self) -> None:
        pass  # stage 2 replicates every write as it happens

    async def on_replicate(self, msg: Message) -> None:
        for key, version, value in msg.body["items"]:
            self.keep(key, version, value)
        self.reply(msg, {"type": "replicate_ok"})

    # ---- stage 2: every region takes writes

    async def replicate(self, key: str, version: float, value: int) -> bool:
        """Send the write to every other region; True as soon as one of them has it."""
        tasks = [asyncio.ensure_future(self.send_to(r, key, version, value)) for r in nearest(self.node_id)]
        for done in asyncio.as_completed(tasks):
            if await done:
                return True
        return False

    async def send_to(self, region: str, key: str, version: float, value: int) -> bool:
        """One write to one region; a hint if it did not answer."""
        body = {"type": "replicate", "items": [(key, version, value)]}
        try:
            await self.rpc(region, body, timeout=TIMEOUT)
            return True
        except (TimeoutError, RPCError):
            hints = self.hints[region]
            if key not in hints or version > hints[key][0]:
                hints[key] = (version, value)  # hand it over later
            return False

    async def hand_off(self) -> None:
        for region, hints in self.hints.items():
            if hints:
                self.spawn(self.hand_over(region, dict(hints)))

    async def hand_over(self, region: str, items: dict[str, tuple[float, int]]) -> None:
        body = {"type": "replicate", "items": [(k, v, x) for k, (v, x) in items.items()]}
        try:
            await self.rpc(region, body, timeout=HAND_OFF_TIMEOUT)
        except (TimeoutError, RPCError):
            return
        hints = self.hints[region]
        for k, entry in items.items():
            if hints.get(k) == entry:  # not replaced by a newer one meanwhile
                del hints[k]

    async def on_fetch(self, msg: Message) -> None:
        version, value = self.store.get(msg.body["key"], (0, None))
        self.reply(msg, {"type": "fetch_ok", "version": version, "value": value})

    async def fetch(self, key: str, token: float) -> tuple[float, int] | None:
        """Ask the other regions for `key`; the first answer at least as new as `token` (kept here too)."""

        async def ask(region: str):
            try:
                return await self.rpc(region, {"type": "fetch", "key": key}, timeout=TIMEOUT)
            except (TimeoutError, RPCError):
                return None

        for done in asyncio.as_completed([asyncio.ensure_future(ask(r)) for r in nearest(self.node_id)]):
            reply = await done
            if reply is not None and reply["value"] is not None and reply["version"] >= token:
                self.keep(key, reply["version"], reply["value"])
                return reply["version"], reply["value"]
        return None
