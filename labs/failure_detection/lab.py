"""Lab failure_detection: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "failure_detection",
    "params": {"rate": Param(30.0)},
}

NODES = 8
BEFORE = 15.0  # false deaths are counted from 15 s before an incident ...
AFTER = 5.0  # ... to 5 s after it ends; messages in the 15 s before it

DETECT_MAX = 2.5  # seconds from a crash until some node declares it dead
FALSE_MAX = 0  # healthy nodes declared dead
MSGS_MAX = 10.0  # messages each node sends per second


def stage_of(detect_ok: bool, false_ok: bool, msgs_ok: bool) -> int:
    """Judge the stage from what the first incident showed: 0 fixed timeout, 1 phi accrual, 2 SWIM."""
    if not (detect_ok and false_ok):
        return 0
    if not msgs_ok:
        return 1
    return 2
