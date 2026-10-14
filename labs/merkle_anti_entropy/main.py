"""Lab merkle_anti_entropy: YOUR FILE. Edit it and save; the live window reruns it.

4 replicas (n0 ... n3) of a key/value store, each with a full copy of the same 20,000 keys
("k00000" ... "k19999"), on a network where every message takes ~100 ms. Clients write ~100 keys a
second, each to one replica, which replicates it to the others in batches; they read ~200 keys a
second from any replica that is up.

Replication sometimes misses writes, and nothing tells you: a replica is down longer than its
hint window, a network blip drops a batch, a bad disk loses keys, an old backup is restored over a
key range. Right now nothing repairs them: those replicas stay behind forever, and a read gets an
old version (or nothing) depending on which replica answers.

Do the stages in order, in this file:

  Stage 1  A full scan: every ROUND seconds, send the next peer the version of every key you hold
           (`full_scan`, `sync_keys`). It answers with the entries it has newer and the keys it
           wants (`on_scan`, using `diff`); store the first, send it the second. Every replica
           converges, but each round sends 20,000 entries to find a few hundred differences.
  Stage 2  Merkle trees: keep a hash tree over the key range (`MerkleTree`), updated in `changed`
           on every change. Compare roots with a peer, descend only into the children whose hashes
           differ (`merkle_sync`, `on_hashes`), and sync only the keys of the leaves that differ.
           Choose DEPTH so a leaf holds a handful of keys.

What you get (see labs/merkle_anti_entropy/api.py):
  KEYS, ALL_KEYS, key_of(i), index_of(key)   the key range: key_of(7) == "k00007"
  self.data                     {key: (version, value)}, read-only; a higher version is newer
  self.version(key) -> int      the version this replica holds, 0 if it has none
  self.store(key, version, value)   keep it if it is newer than ours (what repair calls)
  self.changed(key, old, new)   called after every change of self.data; old/new: (version, value) or None
  self.digest(*parts) -> int    a 64-bit hash; costs one unit of hash work per part
  self.peers                    the other replicas
  self.rpc(peer, body)          send a request and wait for the reply (TimeoutError if none)
  self.send(peer, body), self.reply(msg, body), self.every(seconds, fn)   see core/net.py
A message of type "x" calls `async def on_x(self, msg)`. A message costs its entries: one per item
of every list, tuple, set or dict in its body, plus one.

Check yourself:  uv run pytest labs/merkle_anti_entropy
Peek at a solution (after trying!):  labs/merkle_anti_entropy/reference.py
"""

from __future__ import annotations

from labs.merkle_anti_entropy.api import ALL_KEYS, KEYS, Message, Replica, index_of, key_of

ROUND = 2.0  # seconds between two repair rounds, each with the next peer
FANOUT = 16  # stage 2: children per inner node of the tree
DEPTH = 3  # stage 2: levels below the root, so FANOUT ** DEPTH leaves. 1 = 16 leaves of 1,250 keys;
#            3 = 4,096 leaves of ~5 keys; 5 = a million leaves, nearly all empty. Choose well.


# ---------------------------------------------------------------- stage 1: full scan


def diff(mine: dict, theirs: dict) -> tuple[list, list]:
    """Compare two {key: version} maps over the keys in `theirs` (a key missing from `mine` is
    version 0). Return (keys where theirs is newer, keys where mine is newer).

    diff({"k1": 5, "k2": 3}, {"k1": 4, "k2": 7, "k3": 1}) == (["k2", "k3"], ["k1"])
    """
    # Stage 1: walk theirs.items(); compare each version with mine.get(key, 0).
    raise NotImplementedError("TODO stage 1: diff")


# ---------------------------------------------------------------- stage 2: a Merkle tree


class MerkleTree:
    """Stage 2. A hash tree over the key range. Level 0 is the root (one node, index 0); level d
    has FANOUT ** d nodes; level `depth` holds the leaves. Leaf i covers a contiguous slice of the
    key range: key number n is in leaf n * leaves // KEYS.

      leaf_of(key) -> int        the leaf a key is in
      keys_of(leaf) -> list      every key of the range that leaf covers, present or not
      children(i) -> range       the indexes, one level down, of node i's children
      update(key, old, new)      a key changed (old/new: (version, value) or None): fix its leaf
      hash(level, i) -> int      node i's hash at that level, up to date

    Make a change cheap: a leaf's hash is the XOR of digest(key, version, value) of its keys, so
    update() XORs the old digest out and the new one in (XOR twice cancels). An inner node's hash
    is digest(*its children's hashes). Rehash only the ancestors of leaves that changed, and only
    when hash() is asked (keep the changed leaves in a set): never rehash all 20,000 keys.
    """

    def __init__(self, digest, fanout: int = FANOUT, depth: int = DEPTH) -> None:
        self.digest, self.fanout, self.depth = digest, fanout, depth
        self.leaves = fanout ** depth
        self.levels = [[0] * fanout ** d for d in range(depth + 1)]  # levels[d][i]: node i's hash at level d
        self.dirty: set[int] = set()  # leaves changed since their ancestors were hashed

    def leaf_of(self, key: str) -> int:
        raise NotImplementedError("TODO stage 2: MerkleTree.leaf_of")

    def keys_of(self, leaf: int) -> list[str]:
        # The keys n with n * leaves // KEYS == leaf: from ceil(leaf * KEYS / leaves) up to (not
        # including) ceil((leaf + 1) * KEYS / leaves). In integers, ceil(a / b) is -(-a // b).
        raise NotImplementedError("TODO stage 2: MerkleTree.keys_of")

    def children(self, i: int) -> range:
        raise NotImplementedError("TODO stage 2: MerkleTree.children")

    def update(self, key: str, old, new) -> None:
        raise NotImplementedError("TODO stage 2: MerkleTree.update")

    def hash(self, level: int, i: int) -> int:
        # If some leaves changed, rehash their parents, then theirs, up to the root (the parent of
        # node i is i // fanout); then answer from self.levels.
        raise NotImplementedError("TODO stage 2: MerkleTree.hash")


# ---------------------------------------------------------------- the replica


class ReplicaNode(Replica):
    """One replica. Replication is given (api.py); you write the repair.

    Contract:
      - every replica holds the latest version of every key soon after an incident
      - a calm round costs little, and a repair a few entries per key repaired
      - the hash work stays small: update the tree on each change, never rebuild it
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.tree = None  # Stage 2: MerkleTree(self.digest)
        self.turn = 0
        self.every(ROUND, self.repair)

    def changed(self, key, old, new) -> None:
        pass  # Stage 2: self.tree.update(key, old, new)

    async def repair(self) -> None:
        """One round of anti-entropy, every ROUND seconds, with the next peer in turn."""
        peer = self.peers[self.turn % len(self.peers)]
        self.turn += 1
        # Stage 1: await self.full_scan(peer)
        # Stage 2: await self.merkle_sync(peer) instead

    # ---- stage 1: compare every key

    async def full_scan(self, peer: str) -> None:
        raise NotImplementedError("TODO stage 1: full_scan")  # sync_keys with every key: ALL_KEYS

    async def sync_keys(self, peer: str, keys) -> None:
        """Repair `keys` with `peer`, both ways."""
        # Stage 1: reply = await self.rpc(peer, {"type": "scan", "versions": {key: our version}})
        #          (every key in `keys`, 0 for one we do not hold). Store each of reply["newer"]
        #          ({key: (version, value)}) with self.store; then send the peer the entries it
        #          asked for in reply["want"]: {"type": "entries", "entries": {key: self.data[key]}}.
        raise NotImplementedError("TODO stage 1: sync_keys")

    async def on_scan(self, msg: Message) -> None:
        # Stage 1: diff our versions of the keys in msg.body["versions"] with theirs; reply
        #          {"type": "scan_ok", "newer": {key: self.data[key]} for the keys we have newer,
        #           "want": [the keys they have newer]}.
        raise NotImplementedError("TODO stage 1: on_scan")

    async def on_entries(self, msg: Message) -> None:
        for key, (version, value) in msg.body["entries"].items():
            self.store(key, version, value)

    # ---- stage 2: descend the tree where the hashes differ

    async def merkle_sync(self, peer: str) -> None:
        # Stage 2: start at level 0 with nodes [0] (the root). Ask the peer which ones differ:
        #            reply = await self.rpc(peer, {"type": "hashes", "level": level,
        #                                          "hashes": {i: self.tree.hash(level, i) for i in nodes}})
        #          None differ: done, nothing to repair. At the leaves (level == self.tree.depth):
        #          sync_keys(peer, every key of the leaves that differ). Else the children of the
        #          nodes that differ are the next level's nodes.
        raise NotImplementedError("TODO stage 2: merkle_sync")

    async def on_hashes(self, msg: Message) -> None:
        # Stage 2: reply {"type": "hashes_ok", "differ": [i for i, h in msg.body["hashes"].items()
        #          if our hash of node i at level msg.body["level"] != h]}.
        raise NotImplementedError("TODO stage 2: on_hashes")
