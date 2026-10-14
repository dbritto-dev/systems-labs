"""Lab webhook_delivery: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "webhook_delivery",
    "params": {"rate": Param(60.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = 5.0  # events made this long after an incident are judged too
SETTLE = 35.0  # an event made in the window must be delivered this long after it (backoff is capped at 30 s)
P99_SETTLE = 5.0  # the p99 is judged this long after the window

BASELINE_MIN = 0.99  # share of events delivered before the incident
P99_MAX = 1.0  # seconds: p99 from an event being made to its delivery, for the healthy endpoints
WASTE_MAX = 0.10  # share of the workers' time spent on attempts that failed


def stage_of(baseline_ok: bool, lost_ok: bool, order_ok: bool, p99_ok: bool, waste_ok: bool) -> int:
    """Judge the stage from what the first incident (an endpoint whose connections hang) did:
    0 fire once, 1 retries with backoff and a timeout, 2 a queue per endpoint, in order, parked
    while it fails."""
    if not lost_ok:
        return 0
    if not (order_ok and p99_ok and waste_ok):
        return 1
    return 2
