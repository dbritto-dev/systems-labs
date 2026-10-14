"""Lab deadlock_avoidance: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "deadlock_avoidance",
    "params": {"rate": Param(200.0)},
}

SETTLE = 2.5  # wait this long after a window for the last transfers (clients wait 2 s at most)
CHECK = 5.0  # the money is still checked this long after an incident ends

FROZEN = 1.0  # seconds a cycle of waiting transfers lasts before it counts as a deadlock nobody broke
COMPLETED_MIN = 0.99  # transfers started during the incident that completed
P99_MAX = 0.1  # seconds: p99 of the users' transfers started during the incident
RETRIES_MAX = 0.1  # retries per transfer started during the incident


def stage_of(deadlocks_ok: bool, completed_ok: bool, p99_ok: bool, retries_ok: bool, money_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 locks in request order (deadlocks freeze
    the service, or money is lost), 1 lock timeouts with retry (no deadlock lasts, but timeouts,
    retries and slow transfers), 2 one global lock order with a short critical section."""
    if not (deadlocks_ok and money_ok):
        return 0
    if not (completed_ok and p99_ok and retries_ok):
        return 1
    return 2
