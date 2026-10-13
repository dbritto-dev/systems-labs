"""Lab kafka_log: the numbers and how the stage is judged (Fly.io Gossip Glomers #5a-5c).
The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "kafka_log",
    "params": {"rate": Param(30.0)},
}

NODES = 2  # plus lin-kv
BEFORE = 15.0  # seconds measured before each incident (calm)
AFTER = 10.0  # seconds checked after it
MSGS_MAX = 3.0  # messages between nodes and lin-kv per client operation
P99_MAX = 0.1  # seconds for a send, while the incident lasts


def stage_of(unique_ok: bool, polls_ok: bool, commits_ok: bool, msgs_ok: bool, fast_ok: bool) -> int:
    """Judge the stage from what the first incident showed: 0 single node, 1 multi-node, 2 efficient."""
    if not (unique_ok and polls_ok and commits_ok):
        return 0
    if not (msgs_ok and fast_ok):
        return 1
    return 2
