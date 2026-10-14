"""Lab vector_clocks_crdts: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "vector_clocks_crdts",
    "params": {"rate": Param(20.0)},
}

NODES = 5
BEFORE = 15.0  # messages are counted over the 15 s before an incident
AFTER = 10.0  # lost adds and resurrected removes are counted until 10 s after an incident ends
CONVERGE = 5.0  # the replicas must hold the same carts this long after the incident ends

LOST_MAX = 0  # acknowledged adds that vanished
BACK_MAX = 0  # acknowledged removes that came back
SYNC_MIN = 0.99  # share of settled carts that every replica holds the same
MSGS_MAX = 150.0  # messages between replicas per second


def stage_of(lost_ok: bool, back_ok: bool, sync_ok: bool, msgs_ok: bool) -> int:
    """Judge the stage from what the first incident (a partition) showed: 0 last write wins (adds
    lost), 1 vector clocks (nothing lost, but removes come back), 2 a CRDT (converged, nothing lost
    or back, in a bounded number of messages)."""
    if not lost_ok:
        return 0
    if not (back_ok and sync_ok and msgs_ok):
        return 1
    return 2
