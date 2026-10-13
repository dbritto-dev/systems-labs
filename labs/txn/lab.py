"""Lab txn: the numbers, the goals and the stages (Fly.io Gossip Glomers #6a-6c)."""

from core.contract import Param

META = {
    "id": "txn",
    "title": "Transactions",
    "summary": "Gossip Glomers #6: a replicated key/value store with transactions, totally available.",
    "params": {
        "rate": Param(40.0, "client transactions per second"),
    },
}

NODES = 3
KEYS = 100
BEFORE = (15.0, 3.0)  # freshness is measured from 15 s to 3 s before each partition
CAUGHT_UP = (5.0, 10.0)  # ... and again from 5 s to 10 s after it heals
AROUND = (15.0, 5.0)  # intermediate reads are counted from 15 s before to 5 s after

FRESH_MIN = 0.95  # share of keys, on every node, within 1 s of the newest value anywhere
AVAILABLE_MIN = 0.99  # share of transactions answered during a partition
CAUGHT_UP_MIN = 0.99  # freshness after the partition heals
G1B_MAX = 0  # intermediate reads

STAGES = [
    ("Single node",
     "Challenge: writes stay on the node that got them. Send them to the other nodes.",
     "Stage 1 (6b): replicate every write to the other nodes"),
    ("Replicated",
     "Challenge: writes made during a partition are lost for good. Re-send until acked.",
     "Stage 2 (6b): re-send until acked; the newest stamp wins"),
    ("Read uncommitted",
     "Challenge: readers see values a transaction overwrote itself. Replicate whole txns.",
     "Stage 3 (6c): replicate final values per txn, applied at once"),
    ("Read committed",
     "Solved: every node catches up through partitions, and no one sees intermediate values.",
     "All stages done"),
]


def stage_of(fresh_ok: bool, available_ok: bool, caught_up_ok: bool, g1b_ok: bool) -> int:
    """Judge the stage from what the first partition (and the calm before it) showed."""
    if not fresh_ok:
        return 0
    if not (available_ok and caught_up_ok):
        return 1
    if not g1b_ok:
        return 2
    return 3
