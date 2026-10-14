"""Lab quorum_replication: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "quorum_replication",
    "params": {"rate": Param(20.0)},
}

NODES = 5
BEFORE = 15.0  # stale reads are counted from 15 s before an incident to its end
SYNC_AFTER = 10.0  # replicas must agree this long after the incident ends

STALE_MAX = 0  # reads that miss an acknowledged write
ANSWERED_MIN = 0.99  # share of requests answered during the incident
SYNC_MIN = 0.99  # share of settled keys whose replicas agree
MSGS_MAX = 10.0  # messages between nodes per client operation


def stage_of(stale_ok: bool, answered_ok: bool, sync_ok: bool, msgs_ok: bool) -> int:
    """Judge the stage from what the first incident showed: 0 one copy, 1 quorums, 2 quorums + repair."""
    if not (stale_ok and answered_ok):
        return 0
    if not (sync_ok and msgs_ok):
        return 1
    return 2
