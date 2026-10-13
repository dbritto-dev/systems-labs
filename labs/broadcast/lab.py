"""Lab broadcast: the numbers, the goals and the stages (Fly.io Gossip Glomers #3a-3e)."""

from core.contract import Param

META = {
    "id": "broadcast",
    "title": "Broadcast",
    "summary": "Gossip Glomers #3: get every number to all 25 nodes, through partitions, with few messages.",
    "params": {
        "rate": Param(20.0, "client operations per second (half broadcast, half read)"),
    },
}

NODES = 25
BEFORE = (15.0, 3.0)  # measured from 15 s to 3 s before each partition (calm)
AFTER = 5.0  # numbers sent during a partition must be everywhere this long after it heals

REACH_MIN = 0.99  # share of numbers that reach every node
EFFICIENT_MSGS = 30.0  # 3d: messages per operation
EFFICIENT_P50, EFFICIENT_MAX = 0.4, 0.6  # 3d: seconds until every node has a number
BATCHED_MSGS = 20.0  # 3e
BATCHED_P50, BATCHED_MAX = 1.0, 2.0  # 3e

STAGES = [
    ("Single node",
     "Challenge: each node only knows the numbers sent to it. Tell the other nodes.",
     "Stage 1 (3b): send new numbers to your neighbours"),
    ("Multi-node",
     "Challenge: numbers sent during a partition never reach the other side. Retry them.",
     "Stage 2 (3c): re-send until the other node acknowledges"),
    ("Fault tolerant",
     "Challenge: it works, but costs too many messages and is too slow. Make it efficient.",
     "Stage 3 (3d): under 30 msgs/op, p50 < 400 ms, max < 600 ms"),
    ("Efficient",
     "Challenge: under 30 messages per operation. Now under 20: send numbers in batches.",
     "Stage 4 (3e): under 20 msgs/op (p50 < 1 s, max < 2 s)"),
    ("Batched",
     "Solved: every number reaches every node, through partitions, fast and in few messages.",
     "All stages done"),
]


def stage_of(reach_ok: bool, partition_ok: bool, msgs30_ok: bool, fast_ok: bool, msgs20_ok: bool,
             batched_ok: bool) -> int:
    """Judge the stage from what the first partition (and the calm before it) showed."""
    if not reach_ok:
        return 0
    if not partition_ok:
        return 1
    if not (msgs30_ok and fast_ok):
        return 2
    if not (msgs20_ok and batched_ok):
        return 3
    return 4
