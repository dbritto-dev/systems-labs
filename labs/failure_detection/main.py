"""Lab failure_detection: YOUR FILE. Edit it and save; the live window reruns it.

A cluster must agree on who is dead, the way Cassandra, Akka, Consul and Serf do it. 8 nodes sit
on a network where a message takes ~50 ms. Each runs your `Detector` and keeps `self.status`:
what it thinks of every other node, "alive", "suspect" or "dead". A node is out of the cluster
(clients stop going to it) as soon as one healthy node declares it dead.

Right now every node sends a heartbeat to every other node every HEARTBEAT seconds, and declares
a peer dead after TIMEOUT seconds without one. But four links in this cluster run through an old
switch that loses half of their messages, so four heartbeats in a row get lost all the time and
healthy nodes are declared dead. Raise TIMEOUT to 3 s and that stops, but then a node that
really crashed is found 3 s late, and its clients fail all that time.

Do the stages in order, in this file:

  Stage 1  Phi accrual: write `phi(intervals, elapsed)`, keep the last WINDOW intervals between
           each peer's heartbeats, and judge a silence by its phi instead of a fixed timeout:
           suspect from PHI_SUSPECT, dead from PHI_DEAD. A peer whose heartbeats always arrive
           on time is found fast; one behind a lossy link gets the time its history asks for.
  Stage 2  SWIM: heartbeats to everyone cost 7 messages per node every 0.25 s (28 a second, and
           it grows with the cluster). Instead, every PERIOD ping ONE peer, round the ring. No ack
           within PING_TIMEOUT? Ask K other nodes to ping it for you (a `ping_req`): one broken
           link is not a dead node. Nobody got through: mark it "suspect" and give it a last
           chance (ping it and ask every other node, all within SUSPECT_TIMEOUT); still nothing:
           "dead". Any message from a peer means it is alive.

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are, and every node ("n0" ... "n7")
  self.send(dest, {...})           fire and forget
  self.reply(msg, {...})           answer a request
  await self.rpc(dest, {...}, timeout=0.15)  send and wait for the reply (TimeoutError if none)
  self.every(seconds, coroutine_function)    run something periodically
  self.spawn(coroutine)            run something in the background
  self.now()                       the clock

The checker reads `self.status` (a dict: peer id -> "alive", "suspect" or "dead") every 250 ms.

Check yourself:  uv run pytest labs/failure_detection
Peek at a solution (after trying!):  labs/failure_detection/reference.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (stage 2: asyncio.wait, asyncio.as_completed)
import math  # noqa: F401  (stage 1: math.erfc, math.log10)
import random  # noqa: F401  (stage 2: random.Random(node_id).sample for the helpers)
from collections import deque  # noqa: F401  (stage 1: deque(maxlen=WINDOW))

from core.net import Message, Node, RPCError  # noqa: F401

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

    Take the intervals as a normal distribution: their mean and standard deviation (at least
    MIN_STD). phi = -log10(the chance that the next heartbeat comes even later than `elapsed`):
        later = 0.5 * math.erfc((elapsed - mean) / (std * math.sqrt(2)))
        phi = -math.log10(later)      (guard: later can round to 0.0; use max(later, 1e-300))
    phi 1 = a 10% chance it is still coming, phi 3 = 0.1%, phi 20 = practically none.
    No intervals yet: return 0.0.
    """
    raise NotImplementedError("TODO stage 1: phi(intervals, elapsed)")


class Detector(Node):
    """Decides, for every other node, whether it is alive.

    Contract:
      - `self.status[peer]` is ALIVE, SUSPECT or DEAD, for every other node;
      - a peer that crashed must become DEAD within 2.5 s;
      - a healthy peer must never become DEAD (it may be SUSPECT for a while);
      - send fewer than 10 messages per second (this node, on average);
      - a node that comes back from a crash must be ALIVE again when you hear from it.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.peers = [n for n in node_ids if n != node_id]
        self.status = {p: ALIVE for p in self.peers}
        self.last_heard = {p: 0.0 for p in self.peers}
        # Stage 1: self.intervals = {p: deque([HEARTBEAT], maxlen=WINDOW) for p in self.peers}
        # Stage 2: no heartbeats: self.every(PERIOD, ...) to probe one peer per period. Go round
        # the ring starting after yourself (n3 probes n4, n5, n6, n7, n0, n1, n2, n4, ...):
        # since every node does the same, each node is probed by someone every PERIOD.
        self.every(HEARTBEAT, self.tick)

    async def tick(self) -> None:
        for p in self.peers:
            self.send(p, {"type": "heartbeat"})
        for p in self.peers:
            # Stage 1: v = phi(list(self.intervals[p]), self.now() - self.last_heard[p]);
            # DEAD from PHI_DEAD, SUSPECT from PHI_SUSPECT (only if it was ALIVE).
            if self.now() - self.last_heard[p] > TIMEOUT:
                self.status[p] = DEAD

    async def on_heartbeat(self, msg: Message) -> None:
        # Stage 1: first append the interval since the last heartbeat to self.intervals[p]
        # (always, even after a long silence: that is how phi learns a link that loses messages).
        self.last_heard[msg.src] = self.now()
        self.status[msg.src] = ALIVE

    # ---- stage 2: SWIM

    async def on_ping(self, msg: Message) -> None:
        """Stage 2: a peer pings us: it is alive; reply {"type": "ack"}."""
        raise NotImplementedError("TODO stage 2: on_ping")

    async def on_ping_req(self, msg: Message) -> None:
        """Stage 2: ping msg.body["target"] for the node that asked (with msg.body["timeout"], if it
        sent one) and reply {"type": "ping_req_ok", "ok": True or False}."""
        raise NotImplementedError("TODO stage 2: on_ping_req")

    async def reach(self, peer: str, direct: float, indirect: float, k: int = K) -> bool:
        """Stage 2: can anyone reach `peer`?

        Ping it; if it has not answered within `direct` seconds, also send a ping_req to `k` random
        helpers (not `peer`), and give everyone `indirect` more seconds. True as soon as one of them
        answers (a late ack to your own ping counts too).
        Hint: start the ping as a task with asyncio.ensure_future, `await asyncio.wait([task],
        timeout=direct)`, then add a task per helper and loop over asyncio.as_completed(tasks).
        Cancel what is left when you return.

        A probe is then: `reach(peer, PING_TIMEOUT, INDIRECT_TIMEOUT)`; if False and the peer was
        ALIVE: SUSPECT, then `reach(peer, 0.0, SUSPECT_TIMEOUT, k=len(self.peers) - 1)`; if False
        again and it is still SUSPECT: DEAD.
        """
        raise NotImplementedError("TODO stage 2: reach(peer, direct, indirect, k)")
