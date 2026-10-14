"""Lab event_loop_blocking: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "event_loop_blocking",
    "params": {"rate": Param(100.0)},
}

SETTLE = 6.0  # seconds after an incident before it is judged (every request has ended or timed out)
LAG_MAX = 0.050  # seconds: p99 of the event loop's lag during the incident
HEALTH_MAX = 0  # failed health checks during the incident
LIGHT_P99_MAX = 0.100  # seconds: p99 latency of the light requests (a failed one counts as the timeout)
SERVED_MIN = 0.70  # share of the heavy requests (blocking calls) answered in time during the incident
QUEUED_MAX = 50  # calls waiting in the executors' queues, at most, during the incident
WATCHED_MIN = 0.90  # share of the incident's seconds with a lag report from your watchdog


def stage_of(lag_ok: bool, health_ok: bool, light_ok: bool, served_ok: bool, queued_ok: bool,
             watched_ok: bool) -> int:
    """Judge the stage from the first incident (an upload batch: CPU work): 0 blocking calls on the loop,
    1 offloaded to the default thread pool, 2 bounded pools per kind of work and a lag watchdog."""
    if not (lag_ok and health_ok):
        return 0  # the loop stalls: health checks time out
    if not (light_ok and served_ok and queued_ok and watched_ok):
        return 1  # the loop is free, but the work piles up in a queue (or nobody watches the lag)
    return 2
