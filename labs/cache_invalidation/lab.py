"""Lab cache_invalidation: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "cache_invalidation",
    "params": {"rate": Param(300.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
CHECK = 5.0  # the cache is still checked this long after an incident ends
SETTLE = 2.0  # wait this long after a window for slow requests to finish

HIT_MIN = 0.85  # reads served from the cache before the incident
DB_LIMIT = 500.0  # database reads a second it can take
GAUGE_MAX = DB_LIMIT  # database reads a second that fill the server's gauge


def stage_of(hits_ok: bool, phantom_ok: bool, stale_ok: bool, entries_ok: bool, db_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 the cache is written before the database
    (prices that were never saved are served), 1 cache-aside (only saved prices, but a slow fill can
    put an old one back), 2 leases (no stale read, no stale entry, and the cache still works)."""
    if not phantom_ok:
        return 0
    if not (stale_ok and entries_ok and hits_ok and db_ok):
        return 1
    return 2
