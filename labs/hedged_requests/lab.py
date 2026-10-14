"""Lab hedged_requests: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "hedged_requests",
    "params": {"rate": Param(100.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = (3.0, 13.0)  # requests started this long after an incident must be fast again

TAIL_MAX = 0.050  # seconds: the p99 of a read before and after an incident
EXTRA_MAX = 0.10  # extra calls per read during an incident (copies beyond the first)
WASTE_MAX = 0.05  # share of the replicas' time spent on calls nobody waits for any more
SERVED_MIN = 0.99  # reads answered (right) before the user's deadline, during an incident


def stage_of(tail_ok: bool, extra_ok: bool, waste_ok: bool, served_ok: bool, back_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 one call ... 2 hedge + budget + cancel."""
    if not tail_ok:
        return 0
    if not (extra_ok and waste_ok and served_ok and back_ok):
        return 1
    return 2
