"""Lab merkle_anti_entropy: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "merkle_anti_entropy",
    "params": {"rate": Param(100.0)},
}

REPLICAS = 4  # n0..n3, each a full copy of the 20,000 keys
SETTLE = 0.5  # a write this recent is still replicating: not divergent, and not a stale read yet
REPAIR_S = 15.0  # every divergent key must be repaired within this long after an incident ends
STALE_FOR = 10.0  # reads are checked for this long once that time is up: they must agree by then
BEFORE = 15.0  # hash work is measured over the 15 s before an incident (calm)

STALE_MAX = 0.002  # share of those reads that return an older version than the latest
SENT_MAX = 150.0  # repair entries sent (keys, versions, hashes) per key repaired, from the incident's start
#                   until REPAIR_S after its end
HASH_MAX = 10_000.0  # hash work per second on the busiest replica


def stage_of(fixed_ok: bool, stale_ok: bool, sent_ok: bool, hash_ok: bool) -> int:
    """Judge the stage from what the first incident (n2 down, hints overflow) showed: 0 no repair
    (it stays divergent), 1 a full scan (repaired, but every key crosses the network every round,
    or the tree is rebuilt from scratch), 2 Merkle trees (repaired, cheap)."""
    if not (fixed_ok and stale_ok):
        return 0
    if not (sent_ok and hash_ok):
        return 1
    return 2
