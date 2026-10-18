"""Lab kafka_style_log: the numbers and how the stage is judged (Fly.io Gossip Glomers #5a-5c).
The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "kafka_style_log",
    "params": {"rate": Param(30.0)},
}

NODES = 2  # plus the store (lin-kv and seq-kv)
BEFORE = 15.0  # seconds measured before each incident (calm)
AFTER = 10.0  # seconds checked after it
ANSWERED_MIN = 0.99  # client operations answered (not an error or a timeout), in the calm
MSGS_MAX = 3.0  # messages between nodes and the store per client operation
P99_MAX = 0.1  # seconds for a send, while the incident lasts


def stage_of(answered_ok: bool, unique_ok: bool, polls_ok: bool, commits_ok: bool, msgs_ok: bool,
             fast_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed:
    0 nothing yet, 1 single node, 2 multi-node, 3 efficient."""
    if not answered_ok:
        return 0
    if not (unique_ok and polls_ok and commits_ok):
        return 1
    if not (msgs_ok and fast_ok):
        return 2
    return 3
