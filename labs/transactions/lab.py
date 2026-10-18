"""Lab transactions: the numbers and how the stage is judged (Fly.io Gossip Glomers #6a-6c).
The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "transactions",
    "params": {"rate": Param(40.0)},
}

NODES = 3
KEYS = 100
BEFORE = (15.0, 3.0)  # freshness is measured from 15 s to 3 s before each partition
CAUGHT_UP = (5.0, 10.0)  # ... and again from 5 s to 10 s after it heals
AROUND = (15.0, 5.0)  # intermediate reads are counted from 15 s before to 5 s after

FRESH_MIN = 0.95  # share of keys, on every node, within 1 s of the newest value anywhere
AVAILABLE_MIN = 0.99  # share of transactions answered during a partition
CAUGHT_UP_MIN = 0.99  # freshness after the partition heals
G0_MAX = 0  # dirty writes: read uncommitted (6b) already forbids them
G1_MAX = 0  # aborted, intermediate and circular reads (G1a, G1b, G1c): read committed (6c) forbids them


def stage_of(fresh_ok: bool, available_ok: bool, caught_up_ok: bool, g0_ok: bool, g1_ok: bool) -> int:
    """Judge the stage from what the first partition (and the calm before it) showed:
    0 single node, 1 replicated, 2 read uncommitted (no G0), 3 read committed (no G0, G1a, G1b, G1c)."""
    if not fresh_ok:
        return 0
    if not (available_ok and caught_up_ok and g0_ok):
        return 1
    if not g1_ok:
        return 2
    return 3
