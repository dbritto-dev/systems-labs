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

ANSWER_MIN = 0.99  # 3a: share of client requests answered right (broadcast_ok, a full read_ok)
REACH_MIN = 0.99  # share of numbers that reach every node
NUMBERS_MAX = 30.0  # 3b: average numbers per message between nodes (not the whole set every time)
EFFICIENT_MSGS = 30.0  # 3d: messages per operation
EFFICIENT_P50, EFFICIENT_MAX = 0.4, 0.6  # 3d: seconds until every node has a number
BATCHED_MSGS = 20.0  # 3e
BATCHED_P50, BATCHED_MAX = 1.0, 2.0  # 3e


def stage_of(answer_ok: bool, reach_ok: bool, numbers_ok: bool, partition_ok: bool, msgs30_ok: bool,
             fast_ok: bool, msgs20_ok: bool, batched_ok: bool) -> int:
    """Judge the stage from what the first partition (and the calm before it) showed:
    0 nothing yet, 1 single node, 2 multi-node, 3 fault tolerant, 4 efficient, 5 batched.

    Like Fly.io's 3b, multi-node means the numbers reach every node without sending the whole set in
    every message. Like Fly.io's 3e, stage 5 trades speed for fewer messages: it needs < 20 messages per
    operation and p50 < 1 s / max < 2 s, not 3d's 400/600 ms (a node that batches every half second is
    stage 5)."""
    if not answer_ok:
        return 0
    if not (reach_ok and numbers_ok):
        return 1
    if not partition_ok:
        return 2
    if msgs20_ok and batched_ok:
        return 5
    if msgs30_ok and fast_ok:
        return 4
    return 3
