"""Lab consistent_hashing: YOUR FILE. Edit it and save; the live window reruns it.

Eight cache servers (c0 ... c7) sit in front of a slow database. Every read goes to
the server that `Router.node_for(key)` picks; a miss goes on to the database. Now and
then the cluster changes: a node dies, the autoscaler adds one, a deploy restarts one.
Right now `Router` uses hash(key) % N, so when N changes almost every key moves to a
different server, which has never seen it: a storm of misses hits the database.

Do the stages in order, in this file:

  Stage 1  A hash ring: put every node on a circle at stable_hash(node); a key belongs
           to the first node clockwise from stable_hash(key). Now a change moves only
           the keys of the node that came or went (about 1/N of them).
  Stage 2  Virtual nodes: put every node on the ring many times (say 200 points,
           at stable_hash(f"{node}#{i}")), so every node owns a fair share of keys.

Check yourself:  uv run pytest labs/consistent_hashing
Peek at a solution (after trying!):  labs/consistent_hashing/reference.py
"""

from __future__ import annotations

import bisect
import hashlib


def stable_hash(text: str) -> int:
    """A 64-bit hash that is the same in every process and every run.

    (Python's own hash() of a string changes from one process to the next.)
    """
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


class Router:
    """Picks the cache server for a key.

    Contract:
      - `Router(nodes)` starts with these node names, e.g. ["c0", ..., "c7"].
      - `node_for(key)` returns one of the nodes in the cluster right now.
      - `add(node)` and `remove(node)` are called when the cluster changes.
      - The same key must keep going to the same node while the cluster does not change.
    """

    def __init__(self, nodes: list[str]) -> None:
        self.nodes = list(nodes)
        # Stage 1: build the ring instead: a sorted list of (stable_hash(node), node).
        # Stage 2: many points per node: (stable_hash(f"{node}#{i}"), node) for i in range(200).

    def add(self, node: str) -> None:
        self.nodes.append(node)
        # Stage 1: add the node's point(s) to the ring, keeping it sorted (bisect.insort).

    def remove(self, node: str) -> None:
        self.nodes.remove(node)
        # Stage 1: take the node's point(s) off the ring.

    def node_for(self, key: str) -> str:
        # Stage 1: find the first point >= stable_hash(key) with bisect.bisect_left on the
        # hashes, and wrap around to the first point when you run off the end.
        return self.nodes[stable_hash(key) % len(self.nodes)]


