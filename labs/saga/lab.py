"""Lab saga: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "saga",
    "params": {"rate": Param(20.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
LEAD = 2.0  # sagas started this long before an incident are still running when it starts: judged with it
AFTER = 5.0  # sagas started this long after an incident are timed
SETTLE = 12.0  # wait this long after a window for retries and compensations to finish

BASELINE_MIN = 0.99  # sagas that end consistent (done or rolled back) before the incident
COMPLETED_MIN = 0.95  # orders that could complete (nobody said no) and did
P99_MAX = 1.0  # seconds to finish a saga, for sagas started just after the incident

OOM_AT = 0.6  # an "oom" incident: the orchestrator dies this far into it ...
OOM_DOWN = 2.0  # ... and is back this many seconds later


def downtime(kind: str, t0: float, t1: float) -> tuple[float, float] | None:
    """When the orchestrator is down during an incident, if it is."""
    if kind == "crash":
        return t0, t1
    if kind == "oom":
        at = round(t0 + OOM_AT * (t1 - t0), 1)
        return at, at + OOM_DOWN
    return None


def stage_of(baseline_ok: bool, rolled_ok: bool, consistent_ok: bool, once_ok: bool, completed_ok: bool,
             fast_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 no rollback, 1 compensations,
    2 idempotent, resumable sagas (nothing left half done, every order that can complete does)."""
    if not rolled_ok:
        return 0
    if not (consistent_ok and once_ok and completed_ok):
        return 1
    return 2
