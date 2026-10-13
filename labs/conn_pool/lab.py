"""Lab conn_pool: the numbers, the goals and the stages."""

from core.contract import Param

META = {
    "id": "conn_pool",
    "title": "Connection pool",
    "summary": "Every request opens a database connection. Pool them, cap the pool, fail fast.",
    "params": {
        "rate": Param(100.0, "user requests per second"),
    },
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

STAGES = [
    ("New connection",
     "Challenge: every request opens and closes its own connection. Reuse them in a pool.",
     "Stage 1: keep released connections and hand them out again"),
    ("Pool",
     "Challenge: when the database slows down, the pool grows past its 50 connections. Cap it.",
     "Stage 2: never open more than max_size; wait for a release"),
    ("Bounded pool",
     "Challenge: capped, but requests queue for a connection for seconds. Give up sooner.",
     "Stage 3: raise PoolTimeout after timeout seconds"),
    ("Bounded pool + timeout",
     "Solved: connections are reused, capped below the limit, and waits stay short.",
     "All stages done"),
]


def stage_of(baseline_ok: bool, reuse_ok: bool, errors_ok: bool, wait_ok: bool, recovered_ok: bool) -> int:
    """Judge the stage from what the first incident did."""
    for stage, ok in enumerate((reuse_ok, errors_ok, wait_ok)):
        if not ok:
            return stage
    return 3
