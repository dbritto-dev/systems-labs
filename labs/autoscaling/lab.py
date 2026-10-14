"""Lab autoscaling: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "autoscaling",
    "params": {"rate": Param(120.0)},
}

TARGET_RPS = 10.0  # requests/s per instance at the headroom target (half of what a warm one can do)
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
SETTLE = 3.0  # seconds after a window closes before it is judged (every request ends within 2 s)
HEADROOM_WINDOW = 20.0  # the headroom is judged over the last 20 s of an incident
AFTER = 60.0  # flaps and cost are counted from the start of an incident to 60 s after its end
FLAP_WINDOW = 30.0  # instances added then removed (or removed then added) within 30 s are a flap

BASELINE_MIN = 0.99  # served share before the incident
SERVED_MIN = 0.99  # served share during the incident (the rest timed out: 504)
P99_MAX = 1.0  # seconds: p99 latency of the requests started during the incident
HEADROOM_MIN = 0.50  # spare capacity over the traffic at the end of the incident (the target: 100%)
FLAPS_MAX = 2  # instances that flapped (added and removed again within FLAP_WINDOW)
COST_MAX = 0.50  # instance-seconds over the ideal fleet (the traffic at TARGET_RPS per instance, rounded up)


def stage_of(scaled_out: bool, baseline_ok: bool, served_ok: bool, p99_ok: bool, headroom_ok: bool,
             flaps_ok: bool, cost_ok: bool) -> int:
    """Judge the stage from what the first incident (a surge) did: 0 a fixed fleet, 1 CPU thresholds,
    2 target tracking."""
    if not scaled_out:
        return 0  # the fleet never grew while the traffic doubled
    if not all((baseline_ok, served_ok, p99_ok, headroom_ok, flaps_ok, cost_ok)):
        return 1  # it grows, but one instance at a time (behind the surge), or it flaps, or overshoots
    return 2
