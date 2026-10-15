"""Lab rate_limiting: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "rate_limiting",
    "params": {"rate": Param(100.0)},
}

CLIENTS = 20
CAPACITY = 150.0  # requests/s the backend can do
CLIENT_RATE = 20.0  # what RateLimiter allows one client, per second
BASELINE_WINDOW = 15.0  # seconds before a flood used as the baseline
AFTER_WINDOW = 5.0  # requests started this long after a flood are checked

BASELINE_MIN = 0.99  # served share before the flood
LIMITED_MIN = 0.50  # share of the flooding clients' requests that the limiter turns away
PEAK_MAX = 1.6  # most a flooding client gets through in any 1 s, vs CLIENT_RATE
OTHERS_MIN = 0.99  # served share of the clients that are not flooding
# served share of requests started just after the flood, for the clients that did not flood. Not 99%:
# the fair share caps each of the 20 clients at 150/20 = 7.5/s (burst 10), and a well-behaved client
# at ~5/s sends a random clump above that now and then, so a correct limiter turns away 0-2.5% of
# normal requests in a 5 s window (stages 1-2, capped at 20/s, never do). A limiter that keeps
# punishing everyone after a flood falls far below.
SERVED_MIN = 0.97

def stage_of(baseline_ok: bool, limited_ok: bool, peak_ok: bool, others_ok: bool, served_ok: bool) -> int:
    """Judge the stage from what the first flood did: 0 no limit ... 3 bucket + fair share."""
    for stage, ok in enumerate((limited_ok, peak_ok, others_ok)):
        if not ok:
            return stage
    return 3
