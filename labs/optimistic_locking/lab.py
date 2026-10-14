"""Lab optimistic_locking: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "optimistic_locking",
    "params": {"rate": Param(50.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
SETTLE = 3.0  # wait this long after a window for slow requests to finish

BASELINE_MIN = 0.99  # requests served before the incident
CONFLICT_MAX = 0.01  # share of requests during the incident that end in a 409
P99_MAX = 0.5  # seconds, requests started during the incident
SERVED_MIN = 0.98  # requests started during the incident that were served


def stage_of(baseline_ok: bool, lost_ok: bool, conflicts_ok: bool, fast_ok: bool, served_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 last write wins (updates are lost),
    1 version check (nothing lost, but busy rows answer 409), 2 retry and merge (nothing lost,
    users served)."""
    if not lost_ok:
        return 0
    if not (conflicts_ok and fast_ok and served_ok):
        return 1
    return 2
