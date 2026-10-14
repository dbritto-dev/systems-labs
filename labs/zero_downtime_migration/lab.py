"""Lab zero_downtime_migration: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "zero_downtime_migration",
    "params": {"rate": Param(100.0), "rows": Param(10_000)},
}

WINDOW = 60.0  # seconds: a migration must be done (old column dropped) this long after its window opens
SETTLE = 1.0  # seconds after a window closes before it is judged (every request has ended by then)

ERRORS_MAX = 0  # requests that failed during the window (a column that does not exist)
P99_MAX = 0.040  # seconds: p99 of the writes started during the window
WRONG_MAX = 0  # reads that returned a wrong name, plus rows left with a wrong name at the end
LOAD_LIMIT = 0.72  # above this db load the writes' p99 passes P99_MAX (the dashed line on the chart)


def stage_of(errors_ok: bool, p99_ok: bool, wrong_ok: bool, done_ok: bool) -> int:
    """Judge the stage from what the first migration did: 0 rename in place, 1 expand/contract,
    2 expand/contract with a throttled, verified backfill."""
    if not errors_ok:
        return 0  # instances still on the old release fail: their column is gone
    if not (p99_ok and wrong_ok and done_ok):
        return 1  # nothing fails, but the backfill blocks writes or leaves stale names behind
    return 2
