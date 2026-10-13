"""Lab circuit_breaker: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "circuit_breaker",
    "params": {"rate": Param(100.0), "workers": Param(24)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
DETECT = 3.0  # seconds into an incident before calls to the slow dependency must fail fast
AFTER = (7.0, 12.0)  # requests started this long after an incident must be served again

BASELINE_MIN = 0.99  # served share before the incident
CALL_MAX = 1.2  # seconds: the p99 of calls to the slow dependency (a 1 s timeout passes)
HEALTHY_MIN = 0.99  # served share of requests to the healthy dependency during the incident
FAST_MAX = 0.050  # seconds: the p99 of requests to the slow dependency once detected
RECOVERED_MIN = 0.95  # served share of requests to it after it is back


def stage_of(baseline_ok: bool, calls_ok: bool, healthy_ok: bool, fast_ok: bool, back_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 no protection ... 3 timeouts + bulkhead + breaker."""
    for stage, ok in enumerate((calls_ok, healthy_ok, fast_ok)):
        if not ok:
            return stage
    return 3
