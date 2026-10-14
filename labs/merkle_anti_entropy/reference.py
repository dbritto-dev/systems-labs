"""Lab merkle_anti_entropy: a working solution (stage 2). Read it after you have tried main.py.

Full-scan anti-entropy (stage 1): every round, send a peer the version of every key; it answers
with what it has newer and asks for what we have newer. It repairs everything, but each round
moves 20,000 entries to find a few hundred differences.

Merkle trees (stage 2): each replica keeps a hash tree over its key range, updated on every change
(`changed`). A leaf is the XOR of its keys' digests, so a change is two digests; an inner node is
the digest of its children, rehashed only when someone asks for it after a change. Two replicas
compare roots, descend only into the children that differ, and exchange the keys of the leaves
that differ. A repair costs a few dozen entries per key, however big the key range.
"""

from __future__ import annotations

from labs.merkle_anti_entropy.api import ALL_KEYS, KEYS, Message, Replica, index_of, key_of

ROUND = 2.0  # seconds between two repair rounds, each with the next peer
FANOUT = 16  # children per inner node of the tree
DEPTH = 3  # levels below the root: 16 ** 3 = 4,096 leaves of ~5 keys


# ---------------------------------------------------------------- stage 1: full scan


def diff(mine: dict, theirs: dict) -> tuple[list, list]:
    """(keys where theirs is newer, keys where mine is newer), for the keys in `theirs`."""
    i_need, they_need = [], []
    for key, v in theirs.items():
        m = mine.get(key, 0)
        if v > m:
            i_need.append(key)
        elif m > v:
            they_need.append(key)
    return i_need, they_need


# ---------------------------------------------------------------- stage 2: a Merkle tree


class MerkleTree:
    """A hash tree over the key range: level 0 is the root, level `depth` the leaves."""

    def __init__(self, digest, fanout: int = FANOUT, depth: int = DEPTH) -> None:
        self.digest, self.fanout, self.depth = digest, fanout, depth
        self.leaves = fanout ** depth
        self.levels = [[0] * fanout ** d for d in range(depth + 1)]
        self.dirty: set[int] = set()  # leaves changed since their ancestors were hashed

    def leaf_of(self, key: str) -> int:
        return index_of(key) * self.leaves // KEYS

    def keys_of(self, leaf: int) -> list[str]:
        lo = -(-leaf * KEYS // self.leaves)
        hi = -(-(leaf + 1) * KEYS // self.leaves)
        return [key_of(i) for i in range(lo, hi)]

    def children(self, i: int) -> range:
        return range(i * self.fanout, (i + 1) * self.fanout)

    def update(self, key: str, old, new) -> None:
        """A key changed: XOR its old digest out of its leaf and its new one in."""
        leaf = self.leaf_of(key)
        h = self.levels[self.depth][leaf]
        if old is not None:
            h ^= self.digest(key, *old)
        if new is not None:
            h ^= self.digest(key, *new)
        self.levels[self.depth][leaf] = h
        self.dirty.add(leaf)

    def hash(self, level: int, i: int) -> int:
        if self.dirty:
            self.rehash()
        return self.levels[level][i]

    def rehash(self) -> None:
        """Rehash the ancestors of the changed leaves, bottom up: only those."""
        nodes, f = self.dirty, self.fanout
        for d in range(self.depth - 1, -1, -1):
            below, here = self.levels[d + 1], self.levels[d]
            nodes = {i // f for i in nodes}
            for p in nodes:
                here[p] = self.digest(*below[p * f:(p + 1) * f])
        self.dirty = set()


# ---------------------------------------------------------------- the replica


class ReplicaNode(Replica):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.tree = MerkleTree(self.digest)
        self.turn = 0
        self.every(ROUND, self.repair)

    def changed(self, key, old, new) -> None:
        self.tree.update(key, old, new)

    async def repair(self) -> None:
        """One round of anti-entropy with the next peer."""
        peer = self.peers[self.turn % len(self.peers)]
        self.turn += 1
        await self.merkle_sync(peer)

    # ---- stage 1: compare every key

    async def full_scan(self, peer: str) -> None:
        await self.sync_keys(peer, ALL_KEYS)

    async def sync_keys(self, peer: str, keys) -> None:
        """Send our version of each key; take what the peer has newer, send what it asks for."""
        reply = await self.rpc(peer, {"type": "scan", "versions": {k: self.version(k) for k in keys}})
        for key, (version, value) in reply["newer"].items():
            self.store(key, version, value)
        want = [k for k in reply["want"] if k in self.data]
        if want:
            self.send(peer, {"type": "entries", "entries": {k: self.data[k] for k in want}})

    async def on_scan(self, msg: Message) -> None:
        theirs = msg.body["versions"]
        i_need, they_need = diff({k: self.version(k) for k in theirs}, theirs)
        self.reply(msg, {"type": "scan_ok", "newer": {k: self.data[k] for k in they_need}, "want": i_need})

    async def on_entries(self, msg: Message) -> None:
        for key, (version, value) in msg.body["entries"].items():
            self.store(key, version, value)

    # ---- stage 2: descend the tree where the hashes differ

    async def merkle_sync(self, peer: str) -> None:
        tree = self.tree
        level, nodes = 0, [0]
        while True:
            reply = await self.rpc(peer, {"type": "hashes", "level": level,
                                          "hashes": {i: tree.hash(level, i) for i in nodes}})
            differ = reply["differ"]
            if not differ:
                return  # the same: nothing to repair under these nodes
            if level == tree.depth:
                break
            nodes = [c for i in differ for c in tree.children(i)]
            level += 1
        await self.sync_keys(peer, [k for leaf in differ for k in tree.keys_of(leaf)])

    async def on_hashes(self, msg: Message) -> None:
        level = msg.body["level"]
        differ = [i for i, h in msg.body["hashes"].items() if self.tree.hash(level, i) != h]
        self.reply(msg, {"type": "hashes_ok", "differ": differ})
