"""Lab idempotency: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "idempotency",
    "params": {"rate": Param(40.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = 5.0  # payments started this long after an incident are timed
SETTLE = 8.0  # wait this long after a window for slow tries to finish

BASELINE_MIN = 0.99  # payments answered before the incident
REPLAY_MIN = 0.95  # retries arriving after the first charge that are answered without charging
P99_MAX = 0.5  # seconds, payments started just after the incident


def stage_of(baseline_ok: bool, replay_ok: bool, once_ok: bool, same_ok: bool, fast_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 no idempotency, 1 replays answers,
    2 reserves keys (never a double charge)."""
    if not replay_ok:
        return 0
    if not (once_ok and same_ok):
        return 1
    return 2
