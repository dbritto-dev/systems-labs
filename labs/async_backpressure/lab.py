"""Lab async_backpressure: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param
from labs.async_backpressure.api import (
    ENRICH_BASE, ENRICH_CONCURRENCY, ENRICH_MAX, ENRICH_PER, MEMORY_LIMIT, sink_capacity,
)

META = {
    "id": "async_backpressure",
    "params": {"rate": Param(1000.0)},
}

BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = 10.0  # OOM kills, losses and the memory peak count until this long after an incident
RECOVER = 5.0  # the latency after an incident is that of events arriving from t1 + RECOVER ...
RECOVER_WINDOW = 15.0  # ... for this long
SETTLE = 5.0  # wait this long after a window before judging it (events still on their way)

BASELINE_MIN = 0.95  # events written vs events that arrived, before the incident
PEAK_MAX = 0.80  # the most memory the process may use, as a share of MEMORY_LIMIT
THROUGHPUT_MIN = 0.80  # events written vs what the slowest service could take (or what arrived)
P99_MAX = 1.0  # seconds: end-to-end p99 of the events arriving after the incident

MEMORY_SHOWN = MEMORY_LIMIT  # the gauge is full at the limit


def enrich_capacity(spike: float = 1.0) -> float:
    """Events/s the enrichment service can do at best: full calls, every slot busy."""
    return ENRICH_CONCURRENCY * ENRICH_MAX / ((ENRICH_BASE + ENRICH_MAX * ENRICH_PER) * spike)


def capacity(kind: str | None, severity: float) -> float:
    """Events/s the slowest service can take at best during an incident of this kind."""
    match kind:
        case "slow":
            return min(sink_capacity(severity), enrich_capacity())
        case "spike":
            return min(sink_capacity(), enrich_capacity(severity))
        case "outage":
            return 0.0
    return min(sink_capacity(), enrich_capacity())


def stage_of(baseline_ok: bool, oom_ok: bool, lost_ok: bool, peak_ok: bool, throughput_ok: bool,
             p99_ok: bool) -> int:
    """Judge the stage from what the first incident (the sink 16x slower) did: 0 unbounded queues (the
    memory grows until the process is OOM-killed), 1 bounded queues (no OOM, but the source blocks:
    the upstream's buffer overflows and events are lost, small batches waste the slow sink), 2 credits,
    adaptive batches and counted shedding of LOW events (every goal)."""
    if not (oom_ok and peak_ok):
        return 0
    if not (baseline_ok and lost_ok and throughput_ok and p99_ok):
        return 1
    return 2
