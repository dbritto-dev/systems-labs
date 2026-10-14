"""Lab transactional_outbox: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "transactional_outbox",
    "params": {"rate": Param(50.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = 10.0  # orders saved this long after an incident are timed (the lag goal)
DUP_TAIL = 5.0  # duplicates are counted this long after an incident too (the last restart's)
SETTLE = 15.0  # wait this long after a window for events still on their way

BASELINE_MIN = 0.99  # saved orders shipped before the incident
LAG_MAX = 3.0  # seconds from saving an order to shipping seeing its event, p99, after the incident


def stage_of(baseline_ok: bool, lost_ok: bool, phantom_ok: bool, dup_ok: bool, lag_ok: bool) -> int:
    """Judge the stage from what the first incident (a crash loop) did: 0 dual write (events lost or
    phantom), 1 transactional outbox (every saved order announced, but some twice), 2 idempotent
    consumer (every order shipped exactly once)."""
    if not (lost_ok and phantom_ok):
        return 0
    if not dup_ok:
        return 1
    return 2
