"""Lab g_counter: the numbers, the goals and the stages (Fly.io Gossip Glomers #4)."""

from core.contract import Param

META = {
    "id": "g_counter",
    "title": "Grow-only counter",
    "summary": "Gossip Glomers #4: count adds on 3 stateless nodes with a sequentially consistent KV store.",
    "params": {
        "rate": Param(20.0, "client operations per second (60% add, 40% read)"),
    },
}

NODES = 3
BEFORE = (15.0, 3.0)  # measured from 15 s to 3 s before each incident (calm)
AFTER = (2.0, 7.0)  # reads that start 2-7 s after an incident must be right again

RIGHT_MIN = 0.99  # share of reads inside their band (no lost adds, nothing counted twice)
CONFLICTS_MAX = 0.10  # share of compare-and-swaps that fail
ANSWERED_MIN = 0.99  # share of adds the clients get an answer to in time

STAGES = [
    ("In memory",
     "Challenge: each node counts only its own adds. Keep the count in seq-kv, shared.",
     "Stage 1: read the key, add, write it back"),
    ("Shared key",
     "Challenge: nodes overwrite each other's adds, so the total drifts low. Use CAS.",
     "Stage 2: compare-and-swap, and retry when it fails"),
    ("Compare-and-swap",
     "Challenge: every add fights every other one on one hot key. Give each node its own key.",
     "Stage 3: one key per node; a read adds them up"),
    ("Key per node",
     "Solved: no lost adds, no conflicts: each node writes only its own key.",
     "All stages done"),
]


def stage_of(stored_ok: bool, right_ok: bool, conflicts_ok: bool, answered_ok: bool,
             after_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed."""
    if not stored_ok:
        return 0
    if not right_ok:
        return 1
    if not (conflicts_ok and answered_ok):
        return 2
    return 3
