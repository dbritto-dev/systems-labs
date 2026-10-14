"""Lab failure_detection: a working solution (stage 2). Read it after you have tried main.py.

Phi accrual (stage 1): instead of one timeout for every peer, keep the last intervals between a
peer's heartbeats and ask how unlikely the current silence is, given them. A peer whose
heartbeats always come on time is declared dead quickly; one behind a link that loses half its
messages is given the time its history says it needs.

SWIM (stage 2, what the Detector below does): no more heartbeats to everyone. Every PERIOD each
node pings ONE peer (round the ring), so a node sends a few messages a second however
big the cluster is. No ack in time? Ask K other nodes to ping it for us (ping_req): a broken link
between two nodes is not a dead node. Nobody got through: suspect it, and give it one patient
last chance (SUSPECT_TIMEOUT) before declaring it dead. Any message from a peer means it is alive.
"""

from __future__ import annotations

import asyncio
import math
import random

from core.net import Message, Node, RPCError

ALIVE, SUSPECT, DEAD = "alive", "suspect", "dead"

# Stage 0 and 1: heartbeats.
HEARTBEAT = 0.25  # seconds between heartbeats to every peer
TIMEOUT = 1.0  # stage 0: no heartbeat for this long -> dead
WINDOW = 200  # stage 1: intervals kept per peer
MIN_STD = 0.05  # stage 1: never trust a spread smaller than this (seconds)
PHI_SUSPECT = 3.0  # stage 1: suspect a peer from this phi ...
PHI_DEAD = 20.0  # ... and declare it dead from this one

# Stage 2: SWIM.
PERIOD = 0.4  # seconds between probes (one peer per probe)
PING_TIMEOUT = 0.15  # wait this long for an ack (a round trip takes ~0.1 s)
K = 3  # helpers asked to ping a peer that did not answer
INDIRECT_TIMEOUT = 0.3  # wait this long for the helpers
SUSPECT_TIMEOUT = 0.8  # a suspect's last chance: this long to answer anyone


def phi(intervals: list[float], elapsed: float) -> float:
    """Stage 1: how suspicious a silence of `elapsed` seconds is, given the past `intervals`.

    The intervals are taken as a normal distribution (their mean and standard deviation, at least
    MIN_STD); phi = -log10(the chance that the next heartbeat comes even later than `elapsed`).
    phi 1 = a 10% chance it is still coming, phi 3 = 0.1%, phi 20 = practically none.
    """
    if not intervals:
        return 0.0
    mean = sum(intervals) / len(intervals)
    var = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    std = max(math.sqrt(var), MIN_STD)
    later = 0.5 * math.erfc((elapsed - mean) / (std * math.sqrt(2)))
    return -math.log10(max(later, 1e-300))


class Detector(Node):
    """SWIM: probe one peer per period, indirectly through K helpers, suspect before dead."""

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.peers = [n for n in node_ids if n != node_id]
        self.status = {p: ALIVE for p in self.peers}
        self.rng = random.Random(node_id)
        me = node_ids.index(node_id)
        self.ring = node_ids[me + 1:] + node_ids[:me]  # the peers, starting after this node
        self.turn = 0
        self.checking: set[str] = set()  # suspects getting their last chance
        self.every(PERIOD, self.tick)

    def heard(self, peer: str) -> None:
        """Any message from a peer: it is alive."""
        if peer in self.status:
            self.status[peer] = ALIVE

    async def on_ping(self, msg: Message) -> None:
        self.heard(msg.src)
        self.reply(msg, {"type": "ack"})

    async def on_ping_req(self, msg: Message) -> None:
        """Ping `target` for the node that asked, and tell it whether it answered."""
        self.heard(msg.src)
        target = msg.body["target"]
        ok = await self.ping(target, msg.body.get("timeout", PING_TIMEOUT))
        self.reply(msg, {"type": "ping_req_ok", "ok": ok})

    async def ping(self, peer: str, timeout: float) -> bool:
        try:
            await self.rpc(peer, {"type": "ping"}, timeout=timeout)
        except (TimeoutError, RPCError):
            return False
        self.heard(peer)
        return True

    async def ask(self, helper: str, peer: str, timeout: float) -> bool:
        try:
            body = {"type": "ping_req", "target": peer, "timeout": timeout * 0.6}  # leave time for the relay
            reply = await self.rpc(helper, body, timeout=timeout)
        except (TimeoutError, RPCError):
            return False
        self.heard(helper)
        if reply.get("ok"):
            self.heard(peer)
            return True
        return False

    async def reach(self, peer: str, direct: float, indirect: float, k: int = K) -> bool:
        """Ping `peer`; if it has not answered within `direct`, also ask `k` helpers to try, and give
        everyone `indirect` more seconds (a late ack counts too)."""
        tries = [asyncio.ensure_future(self.ping(peer, direct + indirect))]
        try:
            await asyncio.wait(tries, timeout=direct)
            if tries[0].done() and tries[0].result():
                return True
            helpers = self.rng.sample([p for p in self.peers if p != peer], k)
            tries += [asyncio.ensure_future(self.ask(h, peer, indirect)) for h in helpers]
            for done in asyncio.as_completed(tries):
                if await done:
                    return True
            return False
        finally:
            for t in tries:
                t.cancel()

    def next_target(self) -> str:
        """Round the ring, starting with the node after this one: n3 probes n4, n5, ..., n2. As
        every node does the same, each node is probed by someone every PERIOD."""
        self.turn += 1
        return self.ring[(self.turn - 1) % len(self.ring)]

    async def tick(self) -> None:
        self.spawn(self.probe(self.next_target()))

    async def probe(self, peer: str) -> None:
        if self.status[peer] == DEAD:  # just a ping, to notice when it is back
            await self.ping(peer, PING_TIMEOUT)
            return
        if await self.reach(peer, PING_TIMEOUT, INDIRECT_TIMEOUT):
            return
        if self.status[peer] == ALIVE and peer not in self.checking:
            self.status[peer] = SUSPECT
            self.checking.add(peer)
            try:
                alive = await self.reach(peer, 0.0, SUSPECT_TIMEOUT, k=len(self.peers) - 1)  # ask everyone
            finally:
                self.checking.discard(peer)
            if not alive and self.status[peer] == SUSPECT:
                self.status[peer] = DEAD

