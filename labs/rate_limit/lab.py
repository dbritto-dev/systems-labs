"""Lab rate_limit: the numbers, the goals and the stages."""

from core.contract import Param

META = {
    "id": "rate_limit",
    "title": "Rate limiting",
    "summary": "A few clients flood the API at random. Limit each one so everyone else keeps working.",
    "params": {
        "rate": Param(100.0, "requests per second from all clients together, normally"),
    },
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
SERVED_MIN = 0.99  # served share of requests started just after the flood

STAGES = [
    ("No limit",
     "Challenge: a few clients flood the API and everyone else fails with them. Limit each one.",
     "Stage 1: count each client's requests per 1 s window"),
    ("Fixed window",
     "Challenge: a fixed window lets 2x through when a burst straddles the reset. Smooth it.",
     "Stage 2: replace the window with a token bucket"),
    ("Token bucket",
     "Challenge: each client is capped, but together they still swamp the backend. Share it.",
     "Stage 3: cap each client at its fair share of capacity"),
    ("Bucket + fair share",
     "Solved: each client gets a smooth, fair share, so a flood never hurts the others.",
     "All stages done"),
]


def stage_of(baseline_ok: bool, limited_ok: bool, peak_ok: bool, others_ok: bool, served_ok: bool) -> int:
    """Judge the stage from what the first flood did."""
    for stage, ok in enumerate((limited_ok, peak_ok, others_ok)):
        if not ok:
            return stage
    return 3
