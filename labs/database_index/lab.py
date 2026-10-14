"""Lab database_index: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "database_index",
    "params": {"rate": Param(30.0)},
}

WORKERS = 4  # queries the database runs at once
ROW_COST = 5e-6  # seconds of database time per row read
OVERHEAD = 2e-4  # seconds of database time per query, whatever it reads
TIMEOUT = 2.0  # a user gives up after waiting this long for a worker
QUEUE_MAX = 40  # queued queries that fill the server gauge

BEFORE_WINDOW = 15.0  # rows read are measured in the 15 s before each incident
SETTLE = TIMEOUT + 1.0  # queries started in an incident can end this long after it

BUCKETS = (10, 1_000, 10_000)  # rows read: a few, hundreds, thousands, a full scan (the colours)

LOOKUP_MAX = 5.0  # rows read per login, on average
RANGE_MAX = 2.0  # rows read per row returned by a range query
P99_MAX = 0.100  # seconds
ANSWERED_MIN = 0.99


def stage_of(lookup_ok: bool, range_ok: bool, p99_ok: bool, answered_ok: bool) -> int:
    """Judge the stage from the calm before the first incident: 0 full scans, 1 hash index, 2 both."""
    if not lookup_ok:
        return 0
    if not range_ok:
        return 1
    return 2


def bucket(read: int) -> int:
    """0 a few rows ... 3 tens of thousands (a full scan)."""
    return sum(read > b for b in BUCKETS)
