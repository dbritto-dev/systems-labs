"""Lab n_plus_one: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "n_plus_one",
    "params": {"rate": Param(30.0)},
}

CONNECTIONS = 8  # the database runs this many queries at a time
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER_WINDOW = 5.0  # pages started this long after an incident are checked

BASELINE_MIN = 0.99  # pages served and right before the incident
QUERIES_MAX = 2.0  # queries per page (batching)
P99_MAX = 0.040  # seconds per page during the incident (one round trip, even when slow)
BUSY_MAX = 0.90  # share of the database's connections busy during the incident
SERVED_MIN = 0.99  # pages served after the incident


def stage_of(baseline_ok: bool, queries_ok: bool, busy_ok: bool, p99_ok: bool, served_ok: bool) -> int:
    """Judge the stage from what the first incident (a slow database) did: 0 N+1, 1 batch, 2 join."""
    if not queries_ok:
        return 0
    if not p99_ok:
        return 1
    return 2
