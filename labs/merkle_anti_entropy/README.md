# Lab: Merkle anti-entropy

*[Leer en español](es/README.md)*

Replicas that drift apart silently, in Python on a simulated network: 4 replicas (n0 ... n3) of a
key/value store, each with a full copy of the same 20,000 keys, ~100 ms per message. Clients write
~100 keys a second, each to one replica, which replicates it to the others in batches every 0.1 s;
they read ~200 keys a second from any replica that is up, half of them keys written recently.
Replication misses writes now and then, and nothing tells you. Incidents come at random, like in
production: a replica is down longer than its hint window (the others keep at most 50 hints each
for it, and the writes past that never reach it), a network blip drops the replication batches to
and from one replica, a bad disk loses a few hundred keys on one replica, or an operator restores
an old backup over a key range of one replica. The first incident is always n2 down at 0:20-0:30.

```
uv run python -m live merkle_anti_entropy            # watch it; edit main.py and save
uv run python -m live merkle_anti_entropy --lesson   # the concept, links and a checklist
uv run pytest labs/merkle_anti_entropy               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 No repair (given) | replication only | after an incident a replica stays orange for good, and reads that land on it get old versions |
| 1 Full scan | `diff`, `full_scan`, `sync_keys`, `on_scan`: every round, send a peer every key's version; take what it has newer, send what it asks for | the replicas turn blue within seconds, but the chart is a wall of orange: 20,000 entries a round to find a few hundred differences |
| 2 Merkle trees | `MerkleTree` (updated in `changed`), `merkle_sync`, `on_hashes`: compare roots, descend only where hashes differ, sync the keys of the leaves that differ | a calm round costs a few hashes; after an incident a short burst of orange repairs it |

Goals, judged per incident: every divergent key repaired within 15 s of the end of the incident;
at most 0.2% stale reads in the 10 s after that; at most 150 repair entries sent per key repaired
(from the start of the incident until 15 s after its end); and at most 10,000 units of hash work
a second on the busiest replica (in the 15 s before the incident).

A key is *divergent* on a replica that holds an older version than the latest (or none at all);
writes under 0.5 s old are still replicating and do not count. A read is *stale* when it returns
an older version than the latest. A message costs its *entries*: one per item of every list,
tuple, set or dict in its body (a key with its version, a hash, a node index), plus one. *Hash
work* is one unit per part hashed with `self.digest`.

The tree: level 0 is the root, level `DEPTH` the `16 ** DEPTH` leaves, each a contiguous slice of
the key range. A leaf's hash is the XOR of the digests of its keys, so a change costs two digests
(the old one out, the new one in); an inner node's hash is the digest of its children's hashes,
recomputed only for the ancestors of leaves that changed. The leaf size is yours to choose: with
`DEPTH = 1` each leaf holds 1,250 keys, and one bad key sends all of them; with `DEPTH = 3` a leaf
holds ~5 keys. Rebuilding the tree from all the data every round (like Cassandra's validation
compaction) is cheap on the wire but hashes 20,000 keys each time.

Even in calm, roots rarely match: some writes are still on their way between replicas. That is
why a calm Merkle round still descends and costs a few hundred entries, and why Sent per key
counts the whole window.

How your node talks is in `core/net.py`; what a replica gets (its data, `store`, `changed`,
`digest`, replication and hints) is in `api.py`.
