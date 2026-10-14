"""Lab keyset_pagination: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param
from labs.keyset_pagination.api import PAGE_SIZE

META = {
    "id": "keyset_pagination",
    "params": {"rate": Param(10.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
SETTLE = 3.0  # wait this long after a window for slow pages to finish

BASELINE_MIN = 0.99  # pages answered (not a 400) before the incident
DEEP_PAGE = 10  # a page this far into a client's walk (or further) is a deep page
DEEP_P99_MAX = 0.025  # seconds: p99 of the deep pages asked for during the incident
ROWS_MAX = 2 * PAGE_SIZE  # rows the database reads per page, on average

BUCKETS = (ROWS_MAX, 400, 4_000)  # rows read by a page: fine, hundreds, thousands, more (the colours)


def stage_of(baseline_ok: bool, skipped_ok: bool, dup_ok: bool, deep_ok: bool, rows_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 OFFSET (deep pages read and wait for
    thousands of rows), 1 keyset on created_at (cheap, but posts that share a created_at are
    skipped), 2 a (created_at, id) cursor (cheap, and every post exactly once)."""
    if not (rows_ok and deep_ok):
        return 0
    if not (skipped_ok and dup_ok):
        return 1
    return 2


def bucket(read: int) -> int:
    """0 about a page of rows ... 3 thousands (a deep OFFSET)."""
    return sum(read > b for b in BUCKETS)
