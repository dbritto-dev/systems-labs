"""Lab load_balancing: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "load_balancing",
    "params": {"rate": Param(250.0)},
}

SERVERS = 8
FAIR = 1 / SERVERS  # the share of requests each server gets when they are spread evenly
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
SETTLE = 2.0  # seconds after a window closes before it is judged (every request ends within 1 s)
AFTER_WINDOW = 5.0  # requests started this long after an incident are checked

BASELINE_MIN = 0.99  # served share before the incident
SHARE_MAX = 0.10  # share of the requests sent to the slow server during the incident (fair: 12.5%)
P99_MAX = 0.750  # seconds: p99 latency of the requests started during the incident
SERVED_MIN = 0.99  # served share during the incident (the rest timed out: 504)
FAST = 0.250  # seconds: an answer this fast is a good one (the dashed line, the tiles)
RECOVERED_MIN = 0.95  # share of requests just after the incident served within P99_MAX


def stage_of(baseline_ok: bool, share_ok: bool, p99_ok: bool, served_ok: bool, recovered_ok: bool) -> int:
    """Judge the stage from what the first incident did: 0 round robin, 1 least outstanding requests,
    2 power of two choices."""
    if not share_ok:
        return 0  # the slow server still gets its full share
    if not (p99_ok and served_ok):
        return 1  # it avoids the slow server, but the balancers herd onto whichever server looks idle
    return 2
