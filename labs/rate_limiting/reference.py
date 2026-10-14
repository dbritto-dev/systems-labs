"""Lab rate_limiting: a working solution. Read it after you have tried main.py."""

from __future__ import annotations


class RateLimiter:
    def __init__(self, rate: float = 20.0, burst: float = 10.0, capacity: float = 150.0) -> None:
        self.rate = rate
        self.burst = burst
        self.capacity = capacity
        self.buckets: dict[int, tuple[float, float]] = {}  # client -> (tokens, last refill)
        self.seen: dict[int, float] = {}  # client -> last request time

    def allow(self, client: int, now: float) -> bool:
        # Fair share: never promise more than the backend can do, split across the
        # clients that are active right now.
        self.seen[client] = now
        active = sum(1 for t in self.seen.values() if now - t < 2.0)
        rate = min(self.rate, self.capacity / max(1, active))
        burst = self.burst
        # Token bucket: refill `rate` tokens per second, up to `burst`.
        tokens, last = self.buckets.get(client, (burst, now))
        tokens = min(burst, tokens + (now - last) * rate)
        if tokens < 1.0:
            self.buckets[client] = (tokens, now)
            return False
        self.buckets[client] = (tokens - 1.0, now)
        return True
