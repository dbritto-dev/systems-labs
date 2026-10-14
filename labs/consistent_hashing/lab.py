"""Lab consistent_hashing: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "consistent_hashing",
    "params": {"rate": Param(500.0)},
}

SLOTS = 9  # c0..c8: 8 nodes, plus room for one more when the cluster scales out
BASE_NODES = 8
DB_CAPACITY = 400.0  # database reads/s: 4 at a time, 10 ms each
MOVED_MAX = 3.0  # keys moved on a change: at most 3/N (modulo moves ~(N-1)/N, a ring 1/N to ~2.5/N)
HIT_KEEP = 0.90  # hit ratio right after a change, as a share of the hit ratio before it
DB_PEAK = 2.0  # database reads/s in the AFTER seconds after a change, vs the calm before it
AFTER = 4.0  # seconds after a change that hits and database load are judged
BEFORE = 15.0  # the calm before a change
BALANCE_MAX = 1.4  # keys on the busiest node vs the average


def stage_of(balance_ok: bool, moved_ok: bool, hits_ok: bool, db_ok: bool) -> int:
    """Judge the stage from the first change: 0 modulo (most keys move), 1 hash ring (few keys
    move, but uneven), 2 ring + virtual nodes. Hits and database load show the cost; the stage
    is judged on what the router decides: how many keys move and how evenly they spread."""
    if not moved_ok:
        return 0
    if not balance_ok:
        return 1
    return 2
