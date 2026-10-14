"""Lab caching: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "caching",
    "params": {"rate": Param(200.0), "ttl": Param(30.0)},
}

DB_LIMIT = 400.0  # reads/s the database can do: 8 at a time, 20 ms each
GAUGE_MAX = 64.0  # in-flight + queued reads that fill the server gauge
BASELINE_WINDOW = 15.0  # seconds before a flush used as the baseline
DURING_WINDOW = 5.0  # the first seconds after a flush
AFTER_WINDOW = 10.0  # reads started this long after a flush are timed

HIT_MIN = 0.80  # hit ratio before the flush
DUP_MAX = 0.05  # duplicate loads as a share of database reads after the flush
P99_MAX = 0.100  # seconds

def stage_of(hit_ok: bool, dup_ok: bool, p99_ok: bool) -> int:
    """Judge the stage from what the first flush did: 0 no cache, 1 cache-aside, 2 stampede-safe."""
    if not hit_ok:
        return 0
    if not dup_ok:
        return 1
    return 2
