"""Lab hot_partition: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "hot_partition",
    "params": {"rate": Param(120.0)},
}

SETTLE_IN = 1.0  # the busiest partition is judged from this long after the incident starts
AFTER = 5.0  # operations this long after an incident are judged with it (throttled, p99)
AFTER_START = 8.0  # the after-window, once the key has cooled: from t1 + 8 s ...
AFTER_END = 18.0  # ... to t1 + 18 s
BUSY_MAX = 0.90  # the busiest partition's utilisation, on average over the incident
THROTTLED_MAX = 0.01  # share of operations a partition refused
P99_MAX = 0.100  # seconds, p99 of an operation's latency
FANIN_MAX = 1.10  # store requests per user operation once the key has cooled


def stage_of(busiest_ok: bool, throttled_ok: bool, p99_ok: bool, correct_ok: bool, fanin_ok: bool) -> int:
    """Judge the stage from the first incident (a viral post: increments on one key):
    0 hash by key (its partition melts), 1 salted hot keys (spread, but salted for good),
    2 adaptive: salted only while hot, hot reads cached, folded back when it cools."""
    if not (busiest_ok and throttled_ok and p99_ok and correct_ok):
        return 0
    if not fanin_ok:
        return 1
    return 2
