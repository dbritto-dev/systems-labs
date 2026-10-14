"""Lab geo_replication: YOUR FILE. Edit it and save; the live window reruns it.

A profile and settings service runs in three regions: us, eu and ap, one `RegionNode` each (its
node id is its region). Users live in all three, and the global load balancer sends each one to
their own region. Inside a region a message takes ~1 ms; between regions it crosses an ocean:
us-eu ~70 ms one way, us-ap ~100 ms, eu-ap ~150 ms. Right now every region forwards every read
and write to one primary region, us: users in Europe and Asia wait a round trip across an ocean
for everything, and when us goes down, nobody can do anything.

Do the stages in order, in this file:

  Stage 1  Read replicas. Every region keeps a copy and answers reads from it. Writes still go
           to the primary, which acknowledges them and ships them to the other regions
           asynchronously, in batches every SHIP_EVERY seconds. Reads get fast; but a user in eu
           who saves and reloads can miss their own change, the primary's recent writes exist in
           one region only, and when us is down, nobody can write.
  Stage 2  Writes in every region. Any region takes a write (the user's own, or the next one when
           theirs is down), and acknowledges it only once a second region holds it too (the
           first of the other two to answer): one ocean crossing per write, never two, and no
           acknowledged write lives in one region only. Send the writes a region missed later
           (hints). Session tokens: every request carries the newest version of that key the
           user has written or seen; a region whose copy is older fetches it from the others
           before answering, so nobody misses their own writes, wherever they are served.

How your node talks (see core/net.py):
  self.node_id, self.node_ids      your region ("us", "eu" or "ap"), and all three
  self.reply(msg, {...})           answer a request
  self.send(dest, {...})           fire and forget
  await self.rpc(dest, {...}, timeout=TIMEOUT)   send and wait for the reply (TimeoutError if lost)
  self.every(seconds, coroutine_function)        run something periodically
  self.spawn(coroutine)            run something in the background
  self.now()                       the clock (the same in every region here: fine as a version)
  nearest(region)                  the other regions, nearest first (labs/geo_replication/api.py)

Keep your data in `self.store`, as {key: (version, value)}: the checker looks there.

Check yourself:  uv run pytest labs/geo_replication
Peek at a solution (after trying!):  labs/geo_replication/reference.py
"""

from __future__ import annotations

import asyncio  # stage 2: asyncio.ensure_future, asyncio.as_completed

from core.net import Message, Node, RPCError
from labs.geo_replication.api import REGIONS, nearest  # stage 2: nearest(self.node_id)

PRIMARY = "us"  # stages 0 and 1: the region that takes every write (stage 2 has none)
TIMEOUT = 0.4  # wait this long for another region
SHIP_EVERY = 0.1  # stage 1: send the primary's new writes to the replicas this often
HAND_OFF = 1.0  # stage 2: re-send writes a region missed this often
HAND_OFF_TIMEOUT = 1.0  # stage 2: a batch of hints may cross a slow link


class RegionNode(Node):
    """The service in one region. The users' requests (their app adds the session token):

      read  {key, token}          -> {"type": "read_ok", "value": value or None, "version": version or 0}
      write {key, value, token}   -> {"type": "write_ok", "version": version}

    `token` is the newest version of that key this user has written or read (0 if none). Answer
    {"type": "error", "code": 11} when you cannot serve a request: the app retries once, in the
    next region. Only its owner writes a key, one request at a time. `self.store[key] =
    (version, value)`: what this region holds. A newer version always wins (`keep`).
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple[float, int]] = {}  # key -> (version, value)
        self.log: list[tuple[str, float, int]] = []  # stage 1: written here, not shipped yet
        self.hints: dict[str, dict[str, tuple[float, int]]] = {r: {} for r in REGIONS if r != node_id}
        # Stage 1: self.every(SHIP_EVERY, self.ship)
        # Stage 2: self.every(HAND_OFF, self.hand_off) instead

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
        # Stage 1: answer from self.store, in every region: version, value = self.store.get(key, (0, None)).
        # Stage 2: if that version is older than msg.body["token"], `await self.fetch(key, token)` first;
        #          if no region has it, answer error 11.
        if self.node_id != PRIMARY:
            await self.forward(msg, PRIMARY)
            return
        version, value = self.store.get(msg.body["key"], (0, None))
        self.reply(msg, {"type": "read_ok", "value": value, "version": version})

    async def on_write(self, msg: Message) -> None:
        # Stage 1: at the primary, also append (key, version, value) to self.log for ship().
        # Stage 2: in every region: keep it, then `await self.replicate(key, version, value)`; reply
        #          write_ok if it returned True, else error 11. Make the version newer than the token:
        #          max(self.now(), token + 1e-6).
        if self.node_id != PRIMARY:
            await self.forward(msg, PRIMARY)
            return
        key, value = msg.body["key"], msg.body["value"]
        version = self.now()
        self.keep(key, version, value)
        self.reply(msg, {"type": "write_ok", "version": version})

    # ---- stage 1: replicas in every region

    async def ship(self) -> None:
        """Stage 1. At the primary, every SHIP_EVERY seconds: send what self.log holds to every other
        region in one message, {"type": "replicate", "items": [(key, version, value), ...]} with
        self.send (fire and forget: asynchronous replication), and empty the log."""
        raise NotImplementedError("TODO stage 1: ship()")

    async def on_replicate(self, msg: Message) -> None:
        """Stage 1. Keep every (key, version, value) in msg.body["items"], then reply
        {"type": "replicate_ok"} (stage 2 waits for that answer; in stage 1 nobody does)."""
        raise NotImplementedError("TODO stage 1: on_replicate()")

    # ---- stage 2: every region takes writes

    async def replicate(self, key: str, version: float, value: int) -> bool:
        """Stage 2. Send the write to every other region at once (`self.send_to`, one task each:
        asyncio.ensure_future) and return True as soon as one of them answers True (use
        asyncio.as_completed); False if neither does. Do not wait for the second one."""
        raise NotImplementedError("TODO stage 2: replicate()")

    async def send_to(self, region: str, key: str, version: float, value: int) -> bool:
        """Stage 2. One write to one region: an rpc {"type": "replicate", "items": [(key, version,
        value)]} with timeout=TIMEOUT. True if it answered. If not (TimeoutError or RPCError), keep a
        hint, self.hints[region][key] = (version, value) (unless it already has a newer one), and
        return False."""
        raise NotImplementedError("TODO stage 2: send_to()")

    async def hand_off(self) -> None:
        """Stage 2. Every HAND_OFF seconds: for each region with hints, `self.spawn(self.hand_over(
        region, dict(hints)))` (a copy: new hints may arrive meanwhile)."""
        raise NotImplementedError("TODO stage 2: hand_off()")

    async def hand_over(self, region: str, items: dict[str, tuple[float, int]]) -> None:
        """Stage 2. Send the hints in one rpc {"type": "replicate", "items": [...]} with
        timeout=HAND_OFF_TIMEOUT. If it answered, forget each hint that is still the one you sent."""
        raise NotImplementedError("TODO stage 2: hand_over()")

    async def on_fetch(self, msg: Message) -> None:
        """Stage 2. Reply {"type": "fetch_ok", "version": version, "value": value} from self.store
        ((0, None) if you do not have the key)."""
        raise NotImplementedError("TODO stage 2: on_fetch()")

    async def fetch(self, key: str, token: float) -> tuple[float, int] | None:
        """Stage 2. Ask the other regions for key at once (an rpc {"type": "fetch", "key": key} each,
        timeout=TIMEOUT). Return (version, value) from the first answer with a value whose version
        is at least token, after keeping it here too; None if no answer has it."""
        raise NotImplementedError("TODO stage 2: fetch()")

