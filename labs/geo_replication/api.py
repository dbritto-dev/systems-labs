"""What your RegionNode gets: three regions, far apart, on a simulated network (core/net.py).

Think of a profile and settings service run in three cloud regions: the US (us), Europe (eu) and
Asia-Pacific (ap). Each region runs one `RegionNode` (its node id is the region: "us", "eu" or
"ap"). Inside a region a message takes ~1 ms; between regions it crosses an ocean:

    us <-> eu    ~70 ms one way      (a round trip: ~140 ms)
    us <-> ap   ~100 ms one way      (~200 ms)
    eu <-> ap   ~150 ms one way      (~300 ms)

each ±20%. `nearest(region)` lists the other regions, nearest first.

Users live in all three. The global load balancer (GeoDNS) sends each user to their own region.
When a region is down, it notices within ~1 s and sends that region's users to the next one in
`FAILOVER` (us -> eu, eu -> us, ap -> us), and back 0.5 s after the region recovers (DNS caches
make both gradual, over 4 s). The user's app also retries once, in that next region, when a request
times out (0.6 s) or gets an error, and then sends its reads (or writes) there first for 3 s.

A region serves CAPACITY reads and writes a second (requests of type "read" or "write", from users
or forwarded by another region; your other messages are free). More than that and they queue; a
request that would wait more than 0.5 s is shed (dropped) by the region's load balancer.
"""

from __future__ import annotations

REGIONS = ("us", "eu", "ap")
ONE_WAY = {("us", "eu"): 0.070, ("us", "ap"): 0.100, ("eu", "ap"): 0.150}  # seconds, one way
IN_REGION = 0.001  # seconds, one way, inside a region
JITTER = 0.2  # every delay varies ±20%
CAPACITY = 320.0  # reads and writes a second one region serves
MAX_QUEUE = 0.5  # seconds of queued work above which a region sheds requests
FAILOVER = {"us": "eu", "eu": "us", "ap": "us"}  # where a region's users go when it is down

__all__ = ["CAPACITY", "FAILOVER", "REGIONS", "between", "nearest"]


def between(a: str, b: str) -> float:
    """The one-way delay between two regions (before jitter), in seconds."""
    if a == b:
        return IN_REGION
    return ONE_WAY.get((a, b)) or ONE_WAY[(b, a)]


def nearest(region: str) -> list[str]:
    """The other regions, nearest first: nearest("eu") == ["us", "ap"]."""
    return sorted((r for r in REGIONS if r != region), key=lambda r: between(region, r))
