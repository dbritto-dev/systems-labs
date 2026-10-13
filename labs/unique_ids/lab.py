"""Lab unique_ids (Fly.io Gossip Glomers #1 and #2): the numbers and how the stage is judged.
The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "unique_ids",
    "params": {"rate": Param(30.0)},
}

NODES = 5
BEFORE = 15.0  # the calm measured before each incident
ECHO_MIN = 0.99  # echo requests answered correctly
AVAILABLE_MIN = 0.99  # generate requests answered during the incident
COMPACT_MIN = 0.99  # ids that are 64-bit ints
ORDERED_MIN = 0.99  # ids larger than every id handed out at least 1 s before
ORDER_GAP = 1.0  # seconds: "roughly ordered by time"
REPLY_JITTER = 0.05  # replies from one node this close together may arrive swapped


def stage_of(echo_ok: bool, unique_ok: bool, available_ok: bool, compact_ok: bool, ordered_ok: bool,
             monotonic_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed:
    0 nothing yet, 1 echo, 2 unique ids, 3 Snowflake ids."""
    if not echo_ok:
        return 0
    if not (unique_ok and available_ok):
        return 1
    if not (compact_ok and ordered_ok and monotonic_ok):
        return 2
    return 3
