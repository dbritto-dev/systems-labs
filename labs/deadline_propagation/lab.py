"""Lab deadline_propagation: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "deadline_propagation",
    "params": {"rate": Param(40.0), "connections": Param(3)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
TAIL = 3.0  # wasted work is counted for requests that reach a service up to this long after it

BASELINE_MIN = 0.99  # served share before the incident
WASTE_MAX = 0.05  # share of the services' own work done after its user had left
SERVED_MIN = 0.80  # served during the incident, vs what the db could do (or users asked, if less)
OVERRUN_MAX = 0.010  # seconds: the p99 of how long a caller kept waiting after its user had left


def stage_of(baseline_ok: bool, waste_ok: bool, served_ok: bool, overrun_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 per-hop timeouts ... 2 skip late work."""
    if not overrun_ok:
        return 0
    if not (waste_ok and served_ok):
        return 1
    return 2
