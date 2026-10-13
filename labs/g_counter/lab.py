"""Lab g_counter (Fly.io Gossip Glomers #4): the numbers and how the stage is judged.
The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "g_counter",
    "params": {"rate": Param(20.0)},
}

NODES = 3
BEFORE = (15.0, 3.0)  # measured from 15 s to 3 s before each incident (calm)
AFTER = (2.0, 7.0)  # reads that start 2-7 s after an incident must be right again

RIGHT_MIN = 0.99  # share of reads inside their band (no lost adds, nothing counted twice)
CONFLICTS_MAX = 0.10  # share of compare-and-swaps that fail
ANSWERED_MIN = 0.99  # share of adds the clients get an answer to in time

def stage_of(stored_ok: bool, right_ok: bool, conflicts_ok: bool, answered_ok: bool,
             after_ok: bool) -> int:
    """Judge the stage from the first incident: 0 in memory ... 3 key per node."""
    if not stored_ok:
        return 0
    if not right_ok:
        return 1
    if not (conflicts_ok and answered_ok):
        return 2
    return 3
