"""Lab two_phase_commit: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "two_phase_commit",
    "params": {"rate": Param(10.0)},
}

SHARDS = 3
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
LEAD = 1.0  # transfers started this long before an incident are still running when it starts: judged with it
RESOLVE = 3.0  # in-doubt transfers must be resolved this long after the incident ends (everything is back)
AFTER = 5.0  # transfers started this long after an incident are counted for "completed"
SETTLE = 6.0  # wait this long after a window for decisions to arrive

BASELINE_MIN = 0.95  # transfers committed before the incident
COMPLETED_MIN = 0.90  # transfers started just after the incident that commit

# The first incident: shard n2 is busy (lock timeouts), and the coordinator, full of waiting transfers,
# is OOM-killed while it sends a commit decision, then restarted.
CRASH_AT = 0.6  # this far into it the coordinator dies ...
CRASH_BACK = 0.9  # ... and is back this far into it


def downtime(kind: str, t0: float, t1: float) -> tuple[float, float] | None:
    """When the coordinator is down during an incident, if it is."""
    if kind == "coord_crash":
        return t0, t1
    if kind == "overload":
        return round(t0 + CRASH_AT * (t1 - t0), 1), round(t0 + CRASH_BACK * (t1 - t0), 1)
    return None


def stage_of(baseline_ok: bool, rolled_ok: bool, partial_ok: bool, money_ok: bool, doubt_ok: bool,
             completed_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 one shard at a time, 1 two-phase commit,
    2 two-phase commit with a decision log and recovery (nothing partial, nothing left in doubt)."""
    if not rolled_ok:
        return 0
    if not (partial_ok and money_ok and doubt_ok and completed_ok):
        return 1
    return 2
