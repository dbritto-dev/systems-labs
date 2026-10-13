"""Lab unique_ids: the numbers, the goals and the stages (Fly.io Gossip Glomers #1 and #2)."""

from core.contract import Param

META = {
    "id": "unique_ids",
    "title": "Unique IDs",
    "summary": "Gossip Glomers #1-2: echo, then IDs unique across 5 nodes, through partitions and clock jumps.",
    "params": {
        "rate": Param(30.0, "client requests per second (20% echo, 80% generate)"),
    },
}

NODES = 5
BEFORE = 15.0  # the calm measured before each incident
ECHO_MIN = 0.99  # echo requests answered correctly
AVAILABLE_MIN = 0.99  # generate requests answered during the incident
COMPACT_MIN = 0.99  # ids that are 64-bit ints
ORDERED_MIN = 0.99  # ids larger than every id handed out at least 1 s before
ORDER_GAP = 1.0  # seconds: "roughly ordered by time"
REPLY_JITTER = 0.05  # replies from one node this close together may arrive swapped

STAGES = [
    ("Nothing yet",
     "Challenge: the nodes answer nothing. Start with echo: send the message back.",
     "Stage 1 (#1): reply echo_ok with the same echo"),
    ("Echo",
     "Challenge: now hand out ids that no other request ever got, from any node.",
     "Stage 2 (#2): unique ids, no coordination"),
    ("Unique IDs",
     "Challenge: unique, but not a sortable 64-bit key. Build them from the clock (Snowflake).",
     "Stage 3: ms | node | sequence, never going back"),
    ("Snowflake IDs",
     "Solved: echo works, and ids are unique, 64-bit, time-ordered and never go backwards.",
     "All stages done"),
]


def stage_of(echo_ok: bool, unique_ok: bool, available_ok: bool, compact_ok: bool, ordered_ok: bool,
             monotonic_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed."""
    if not echo_ok:
        return 0
    if not (unique_ok and available_ok):
        return 1
    if not (compact_ok and ordered_ok and monotonic_ok):
        return 2
    return 3
