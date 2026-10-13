"""Lab circuit_breaker: the numbers, the goals and the stages."""

from core.contract import Param

META = {
    "id": "circuit_breaker",
    "title": "Circuit breaker",
    "summary": "One slow dependency takes every worker. Add timeouts, a bulkhead and a circuit breaker.",
    "params": {
        "rate": Param(100.0, "user requests per second"),
        "workers": Param(24, "workers in our service"),
    },
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
DETECT = 3.0  # seconds into an incident before calls to the slow dependency must fail fast
AFTER = (7.0, 12.0)  # requests started this long after an incident must be served again

BASELINE_MIN = 0.99  # served share before the incident
CALL_MAX = 1.2  # seconds: the p99 of calls to the slow dependency (a 1 s timeout passes)
HEALTHY_MIN = 0.99  # served share of requests to the healthy dependency during the incident
FAST_MAX = 0.050  # seconds: the p99 of requests to the slow dependency once detected
RECOVERED_MIN = 0.95  # served share of requests to it after it is back

STAGES = [
    ("No protection",
     "Challenge: one slow dependency holds every worker, so all requests fail. Add timeouts.",
     "Stage 1: give up on a call after TIMEOUT"),
    ("Timeouts",
     "Challenge: slow calls still hold the workers for a second each. Fence each dependency.",
     "Stage 2: a Bulkhead per dependency"),
    ("Timeouts + bulkhead",
     "Challenge: the healthy path is safe, but users still wait 1 s on the slow one. Fail fast.",
     "Stage 3: a CircuitBreaker per dependency"),
    ("Timeouts + bulkhead + breaker",
     "Solved: the slow dependency is fenced off and fails fast, and the rest keeps working.",
     "All stages done"),
]


def stage_of(baseline_ok: bool, calls_ok: bool, healthy_ok: bool, fast_ok: bool, back_ok: bool) -> int:
    """Judge the stage from what the first incident did."""
    for stage, ok in enumerate((calls_ok, healthy_ok, fast_ok)):
        if not ok:
            return stage
    return 3
