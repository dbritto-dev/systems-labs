"""Lab raft: the numbers and how the stage is judged.

The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "raft",
    "params": {"rate": Param(10.0)},
}

NODES = 5
BEFORE = (15.0, 3.0)  # measured from 15 s to 3 s before each incident (calm)
AFTER = 5.0  # a committed command must still be there this long after the incident ends
SETTLE = 3.0  # a command is judged this long after it starts (clients give up after 2 s)

LEADER_MIN = 0.95  # share of the calm with a leader
ELECTION_MAX = 2.0  # seconds until the majority has a leader again
COMMITTED_MIN = 0.99  # share of commands acknowledged and committed (and none acknowledged wrongly)
AVAILABLE_MIN = 0.95  # share of commands acknowledged during the incident


def stage_of(leader_ok: bool, election_ok: bool, committed_ok: bool, safe_ok: bool,
             available_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed:
    0 no leader, 1 leader election, 2 log replication, 3 safe under partitions."""
    if not (leader_ok and election_ok):
        return 0
    if not committed_ok:
        return 1
    if not (safe_ok and available_ok):
        return 2
    return 3
