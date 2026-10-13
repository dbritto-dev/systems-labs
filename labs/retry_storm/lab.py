"""Lab retry_storm: the numbers, the goals and the stages."""

from core.contract import Param

META = {
    "id": "retry_storm",
    "title": "Retry storm",
    "summary": "The service goes down at random. Retry the failed calls without piling on load.",
    "params": {
        "rate": Param(100.0, "user requests per second"),
    },
}

LIMIT = 150.0  # calls/s our service is sized for
GAUGE_MAX = 450.0  # calls/s that fill the server gauge
GAUGE_ORANGE = 1.8  # gauge turns orange above this much load (x what users ask)
BASELINE_WINDOW = 15.0  # seconds before an outage used as the baseline
AFTER_WINDOW = 5.0  # requests started this long after an outage are checked

BASELINE_MIN = 0.99  # served ratio before the outage
RETRIES_MIN = 0.03  # retries as a share of calls during the outage
BACKOFF_MIN = 1.5  # the average wait grows at least this much from one retry round to the next
BACKOFF_SAMPLES = 3  # retries needed in a round to compare it with the next
JITTER_MIN = 0.25  # spread of the wait before the same retry round, across users (stdev / mean)
JITTER_SAMPLES = 5  # retries needed to judge the spread
LOAD_MAX = 1.5  # calls during the outage vs the baseline
SERVED_MIN = 0.90  # served share of requests started just after the outage

STAGES = [
    ("No retry",
     "Challenge: the service goes down at random, and users fail. Retry the failed calls.",
     "Stage 1: retry failed calls in Client"),
    ("Retry",
     "Challenge: retries come straight back and hammer the service. Wait longer each time.",
     "Stage 2: sleep backoff_delay(attempt) between retries (exponential)"),
    ("Retry + backoff",
     "Challenge: every user backs off by the same amount, so retries come in waves. Add jitter.",
     "Stage 3: add full jitter to backoff_delay"),
    ("Retry + backoff + jitter",
     "Challenge: jitter spreads the retries, but they still pile 4x the load on. Cap them.",
     "Stage 4: spend a RetryBudget on every retry"),
    ("Retry + backoff + jitter + budget",
     "Solved: retries back off with jitter and spend a budget, so the load stays flat.",
     "All stages done"),
]


def stage_of(baseline_ok: bool, retries_ok: bool, backoff_ok: bool, jitter_ok: bool, load_ok: bool,
             served_ok: bool) -> int:
    """Judge the stage from what the first outage did."""
    for stage, ok in enumerate((retries_ok, backoff_ok, jitter_ok, load_ok)):
        if not ok:
            return stage
    return 4
