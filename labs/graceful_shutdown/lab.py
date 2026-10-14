"""Lab graceful_shutdown: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "graceful_shutdown",
    "params": {"rate": Param(300.0)},
}

INSTANCES = 6  # the fleet behind the load balancer
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
SETTLE = 6.0  # seconds after a window closes before it is judged (every request ends within 6 s)
KILL_WAIT = 21.0  # after an incident ends, the last instance it stopped may still be killed this late

ERRORS_MAX = 0.001  # share of requests that fail (refused or cut) during the incident: 0.1%
CUT_MAX = 0  # requests and streams cut mid-flight by a shutdown
CAPACITY_MIN = INSTANCES - 1  # instances serving (in the load balancer and accepting) at every moment


def stage_of(baseline_ok: bool, errors_ok: bool, cut_ok: bool, capacity_ok: bool, exited_ok: bool) -> int:
    """Judge the stage from what the first incident (a rolling deploy) did: 0 exit at once, 1 drain,
    2 readiness off first."""
    if not (cut_ok and exited_ok):
        return 0  # requests are still cut mid-flight (an exit at once, or the hard kill)
    if not (errors_ok and capacity_ok):
        return 1  # it drains, but the load balancer still sends it new requests until it notices
    return 2
