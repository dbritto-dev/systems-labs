"""Lab overload: YOUR FILE. Edit it and save; the live window reruns it.

A server does ~100 requests/s and keeps the rest in a queue. Users give up on
a request after 1 s and send it again (twice at most). At random times traffic
spikes or the server loses capacity. Right now the queue has no limit and is
served oldest first: after a spike it is full of requests whose users already
left, the server spends all its time on them, and nobody gets a reply in time
even after the spike is over (a metastable failure).

`Policy` decides three things. Do the stages in order, in this file:

  Stage 1  Bounded queue: in `admit`, reject a request when the queue holds
           MAX_QUEUE already. A rejection is a fast answer: no retry.
  Stage 2  Skip what is too late: in `drop`, return `too_late(request, now)` so
           the server never works on a request whose user will not get the
           reply in time (they already gave up, or are about to).
  Stage 3  Adaptive LIFO: in `newest_first`, return `overloaded(queue_len)` so a
           long queue is served newest first (those users are still waiting).

Check yourself:  uv run pytest labs/overload
Peek at a solution (after trying!):  labs/overload/reference.py
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_QUEUE = 200  # requests the queue may hold (2 s of work at 100/s)
USER_TIMEOUT = 1.0  # seconds a user waits for a reply before giving up
LIFO_AT = 20  # queue length above which the server is "overloaded"
MARGIN = 0.1  # seconds a reply needs to be worth starting: work + the trip back


@dataclass(slots=True)
class Request:
    """One try of one user. `sent_at` is when this try was sent; `attempt` is
    0 for the first try, 1 and 2 for retries."""

    id: int
    sent_at: float
    attempt: int = 0


class Policy:
    """What the server does under load. The scenario makes one and asks it:

      admit(request, queue_len, now)  when a request arrives: False rejects it
                                      at once (the user gets an error, no retry)
      drop(request, now)              when the server is about to work on a
                                      request: True skips it for free
      newest_first(queue_len, now)    when the server picks the next request:
                                      True takes the newest (LIFO), False the
                                      oldest (FIFO)
    """

    def admit(self, request: Request, queue_len: int, now: float) -> bool:
        # Stage 1: return queue_len < MAX_QUEUE
        return True

    def drop(self, request: Request, now: float) -> bool:
        # Stage 2: return too_late(request, now)
        return False

    def newest_first(self, queue_len: int, now: float) -> bool:
        # Stage 3: return overloaded(queue_len)
        return False


def too_late(request: Request, now: float) -> bool:
    """Stage 2. True when a reply can no longer reach the user in time: they give
    up USER_TIMEOUT seconds after `sent_at`, and less than MARGIN is left."""
    raise NotImplementedError("TODO stage 2: too_late(request, now)")


def overloaded(queue_len: int) -> bool:
    """Stage 3. True when the queue is longer than LIFO_AT: serve newest first."""
    raise NotImplementedError("TODO stage 3: overloaded(queue_len)")
