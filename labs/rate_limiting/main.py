"""Lab rate_limiting: YOUR FILE. Edit it and save; the live window reruns it.

20 clients call an API through `RateLimiter`. The backend can do 150
requests/s; normally the clients send ~100/s together. At random times a few
clients flood it in bursts. Right now `RateLimiter` lets everything through,
so the backend overloads and every client's requests fail, not only theirs.

Do the stages in order, in this file (each one replaces the logic of the last):

  Stage 1  Fixed window: at most `rate` requests per client in each 1 s window.
  Stage 2  Token bucket: per client, refill `rate` tokens per second, up to
           `burst`; each request takes one token.
  Stage 3  Fair share: never promise more than the backend can do. Give each
           client at most min(rate, capacity / active clients).

Check yourself:  uv run pytest labs/rate_limiting
Peek at a solution (after trying!):  labs/rate_limiting/reference.py
"""

from __future__ import annotations


class RateLimiter:
    """Decides, for each request, whether it may go to the backend.

    Contract:
      - `allow(client, now)` returns True to let the request through, False to
        turn it away (the client gets a 429 and may try again later).
      - `client` is an int (0-19); `now` is the current time in seconds and only
        goes up.
      - It must answer straight away: no sleeping, no waiting.

    The scenario makes one RateLimiter for all clients, so state you keep on
    `self` (counters, buckets) is shared between them.
    """

    def __init__(self, rate: float = 20.0, burst: float = 10.0, capacity: float = 150.0) -> None:
        self.rate = rate  # requests per second one client may send
        self.burst = burst  # stage 2: the most tokens a bucket holds
        self.capacity = capacity  # stage 3: requests per second the backend can do

    def allow(self, client: int, now: float) -> bool:
        # Stage 1: keep a count per (client, int(now)); allow while the count is
        # below self.rate. Hint: a dict, and only the current window matters.
        #
        # Stage 2: per client keep (tokens, last time). Refill
        # (now - last) * self.rate tokens, never above self.burst; allow if at
        # least one token is left, and take it. A new client starts full.
        #
        # Stage 3: remember when each client was last seen. Count the clients
        # seen in the last 2 s, and use min(self.rate, self.capacity / active)
        # as the refill rate.
        return True
