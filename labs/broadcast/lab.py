"""Lab broadcast (Fly.io Gossip Glomers #3a-3e): the numbers and how the stage is judged.

The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "broadcast",
    "params": {"rate": Param(20.0)},
}

NODES = 25
BEFORE = (15.0, 3.0)  # measured from 15 s to 3 s before each partition (calm)
AFTER = 5.0  # numbers sent during a partition must be everywhere this long after it heals

REACH_MIN = 0.99  # share of numbers that reach every node
EFFICIENT_MSGS = 30.0  # 3d: messages per operation
EFFICIENT_P50, EFFICIENT_MAX = 0.4, 0.6  # 3d: seconds until every node has a number
BATCHED_MSGS = 20.0  # 3e
BATCHED_P50, BATCHED_MAX = 1.0, 2.0  # 3e


def stage_of(reach_ok: bool, partition_ok: bool, msgs30_ok: bool, fast_ok: bool, msgs20_ok: bool,
             batched_ok: bool) -> int:
    """Judge the stage from what the first partition (and the calm before it) showed:
    0 single node, 1 multi-node, 2 fault tolerant, 3 efficient, 4 batched.

    Like Fly.io's 3e, stage 4 trades speed for fewer messages: it needs < 20 messages per operation and
    p50 < 1 s / max < 2 s, not 3d's 400/600 ms (a node that batches every half second is stage 4)."""
    if not reach_ok:
        return 0
    if not partition_ok:
        return 1
    if msgs20_ok and batched_ok:
        return 4
    if msgs30_ok and fast_ok:
        return 3
    return 2
