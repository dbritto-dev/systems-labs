"""Lab distributed_lock: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "distributed_lock",
    "params": {"rate": Param(0.8)},
}

BEFORE = 15.0  # corrupt writes are counted from 15 s before an incident ...
AFTER = 10.0  # ... to 10 s after it; stalls and jobs from its start to 10 s after it

CORRUPT_MAX = 0  # writes from a lost lock that the storage accepted over newer data
STUCK_MAX = 5.0  # seconds: the longest stretch with jobs waiting and none finishing
DONE_MIN = 0.80  # share of the jobs asked for that finished


def stage_of(corrupt_ok: bool, stuck_ok: bool, done_ok: bool) -> int:
    """Judge the stage from what the first incident (a pause) showed: 0 plain lock, 1 leases, 2 fencing."""
    if not stuck_ok:
        return 0
    if not (corrupt_ok and done_ok):
        return 1
    return 2
