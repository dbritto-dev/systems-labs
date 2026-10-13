"""Lab cache: the numbers, the goals and the stages."""

from core.contract import Param

META = {
    "id": "cache",
    "title": "Cache stampede",
    "summary": "Every read waits for a slow database. Cache the hot keys, then survive a cache flush.",
    "params": {
        "rate": Param(200.0, "pages per second (each page reads 3 keys)"),
        "ttl": Param(30.0, "seconds a cached value lives"),
    },
}

DB_LIMIT = 400.0  # reads/s the database can do: 8 at a time, 20 ms each
GAUGE_MAX = 64.0  # in-flight + queued reads that fill the server gauge
BASELINE_WINDOW = 15.0  # seconds before a flush used as the baseline
DURING_WINDOW = 5.0  # the first seconds after a flush
AFTER_WINDOW = 10.0  # reads started this long after a flush are timed

HIT_MIN = 0.80  # hit ratio before the flush
DUP_MAX = 0.05  # duplicate loads as a share of database reads after the flush
P99_MAX = 0.100  # seconds

STAGES = [
    ("No cache",
     "Challenge: every read waits for the database. Keep the hot keys in memory.",
     "Stage 1: cache-aside with a TTL"),
    ("Cache-aside",
     "Challenge: after a flush every miss hits the database at once. Load each key once.",
     "Stage 2: single-flight loads and jittered TTLs"),
    ("Stampede-safe",
     "Solved: hot keys come from memory, and one load per key refills the cache after a flush.",
     "Both stages done"),
]


def stage_of(hit_ok: bool, dup_ok: bool, p99_ok: bool) -> int:
    """Judge the stage from what the first flush did."""
    if not hit_ok:
        return 0
    if not dup_ok:
        return 1
    return 2
