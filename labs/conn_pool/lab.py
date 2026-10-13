"""Lab conn_pool: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "conn_pool",
    "params": {"rate": Param(100.0)},
}

MAX_CONNECTIONS = 50  # the database refuses connections beyond this
CORES = 20  # past this many connections working at once, the database slows down
GAUGE_MAX = MAX_CONNECTIONS  # open connections that fill the server gauge
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
SETTLE = 2.0  # seconds after a window closes before it is judged
AFTER_WINDOW = 5.0  # requests started this long after an incident are checked

BASELINE_MIN = 0.99  # served share before the incident
REUSE_MIN = 0.90  # share of requests that did not open a new connection, before the incident
WAIT_MAX = 1.0  # p99 seconds waiting for a connection during the incident
RECOVERED_MIN = 0.95  # share of requests just after the incident served within WAIT_MAX

def stage_of(baseline_ok: bool, reuse_ok: bool, errors_ok: bool, wait_ok: bool, recovered_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 new connection ... 3 bounded pool + timeout."""
    for stage, ok in enumerate((reuse_ok, errors_ok, wait_ok)):
        if not ok:
            return stage
    return 3
