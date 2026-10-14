"""Lab stream_windowing: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "stream_windowing",
    "params": {"rate": Param(40.0)},
}

# The same numbers as main.py: the lab judges your windows against them.
WINDOW = 10.0  # seconds per window
DELAY = 2.0  # the watermark: the largest event time seen minus this
LATENESS = 30.0  # a window takes late events until the watermark is this far past its end

BASELINE_WINDOW = 20.0  # seconds before an incident used as the baseline
TAIL = 25.0  # events that arrive up to this long after an incident still belong to it
SETTLE = DELAY + LATENESS + 3.0  # a window's count is final this long after its end

BASELINE_MIN = 0.999  # events counted in their own window, in the calm before an incident
EXACT_MIN = 0.99  # windows exactly right at their final count, around an incident
DROPPED_MAX = 0  # events neither in their window's count nor in the side output
LATENCY_MAX = 5.0  # seconds from a window's end to its first result (p99)
STATE_MAX = 6  # windows kept in the processor's state


def stage_of(baseline_ok: bool, exact_ok: bool, dropped_ok: bool, latency_ok: bool, state_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 processing time, 1 event time with a
    watermark (calm windows right, late events dropped), 2 allowed lateness with updates."""
    if not baseline_ok:
        return 0
    if not (exact_ok and dropped_ok and latency_ok and state_ok):
        return 1
    return 2
