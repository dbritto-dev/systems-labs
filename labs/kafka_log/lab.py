"""Lab kafka_log: the numbers, the goals and the stages (Fly.io Gossip Glomers #5a-5c)."""

from core.contract import Param

META = {
    "id": "kafka_log",
    "title": "Kafka log",
    "summary": "Gossip Glomers #5: a replicated Kafka-style log on two nodes; correct first, then cheap.",
    "params": {
        "rate": Param(30.0, "client operations per second"),
    },
}

NODES = 2  # plus lin-kv
BEFORE = 15.0  # seconds measured before each incident (calm)
AFTER = 10.0  # seconds checked after it
MSGS_MAX = 3.0  # messages between nodes and lin-kv per client operation
P99_MAX = 0.1  # seconds for a send, while the incident lasts

STAGES = [
    ("Single node",
     "Challenge: each node hands out its own offsets, so two messages share one. Agree on them.",
     "Stage 1 (5b): keep offsets and messages in lin-kv"),
    ("Multi-node",
     "Challenge: correct, but every send costs ~10 messages and stalls on one hot key.",
     "Stage 2 (5c): fewer round trips, e.g. an owner per key"),
    ("Efficient",
     "Solved: offsets are unique, nothing is lost, and a send costs about one message.",
     "All stages done"),
]


def stage_of(unique_ok: bool, polls_ok: bool, commits_ok: bool, msgs_ok: bool, fast_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed."""
    if not (unique_ok and polls_ok and commits_ok):
        return 0
    if not (msgs_ok and fast_ok):
        return 1
    return 2
