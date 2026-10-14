"""Lab webhook_delivery: YOUR FILE. Edit it and save; the live window reruns it.

A shop platform sends webhooks (order.created, order.paid, order.fulfilled, order.refunded) to
20 customer endpoints, ~60 events a second. WORKERS (24) delivery workers share the work: a
free worker asks `Dispatcher.next(now)` what to send, POSTs it, and reports the answer with
`Dispatcher.done(ev, status, now)`.

Right now the dispatcher is one queue for everyone, and it fires each event once: a failed
POST is given up. When an endpoint is down, its events are lost; when its connections hang,
each POST holds a worker for the HTTP client's 30 s, and soon every worker is stuck there.

Do the stages in order, in this file:

  Stage 1  Retries: wait at most ATTEMPT_TIMEOUT for an answer, and retry every failure later
           with exponential backoff and jitter (`backoff`) instead of giving up.
  Stage 2  A queue per endpoint (`Endpoint`): at most MAX_IN_FLIGHT POSTs to one endpoint, one
           event per order at a time, oldest first (order.paid never before order.created),
           and park an endpoint after DISABLE_AFTER failures in a row: one probe every
           PROBE_EVERY seconds, and the whole backlog replayed once it answers again.

What you get (see labs/webhook_delivery/api.py):
  ev.id, ev.endpoint, ev.key (the order), ev.seq (1 created, 2 paid, 3 fulfilled, 4 refunded),
  ev.type, ev.created, ev.attempts (counted for you: 1 during the first attempt)
  ok(status)        True for a 2xx answer; status is None when there was no answer at all
  self.give_up(ev)  mark it failed for good: it is never delivered

Check yourself:  uv run pytest labs/webhook_delivery
Peek at a solution (after trying!):  labs/webhook_delivery/reference.py
"""

from __future__ import annotations

import heapq  # noqa: F401  (stage 1: a heap of retries)
import random
from collections import deque
from collections.abc import Callable

from labs.webhook_delivery.api import Event, ok

ATTEMPT_TIMEOUT = 2.0  # seconds to wait for one answer: a healthy endpoint answers in ~0.1 s
BACKOFF_BASE = 0.5  # seconds: the most the 1st retry waits; doubles each time
BACKOFF_CAP = 30.0
MAX_IN_FLIGHT = 4  # POSTs in flight to one endpoint at most
DISABLE_AFTER = 5  # failures in a row that park an endpoint
PROBE_EVERY = 5.0  # seconds between tries while an endpoint is parked
MAX_ATTEMPTS = 6  # attempts before one event that keeps failing (poison) is given up


class Endpoint:
    """Stage 2. One customer endpoint: its own queue, its share of the workers, its health.

    Contract:
      - `queue` holds its events not delivered yet, oldest first (the Dispatcher appends them).
      - `pick(now)` returns the event to send now, or None: never more than MAX_IN_FLIGHT POSTs
        in flight to this endpoint, never two events of one order (`ev.key`) at once, and never
        an event while an older event of its order is still in the queue.
      - `succeeded(ev, now)` and `failed(ev, now)` are told how each POST it picked ended.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.queue: list[Event] = []  # not delivered yet, oldest first
        self.retry_at: dict[int, float] = {}  # event id -> not before this time
        self.sending: set[int] = set()  # keys (orders) with a POST in flight
        self.failures = 0  # in a row
        self.parked = False
        self.probe_at = 0.0

    def pick(self, now: float) -> Event | None:
        """Stage 2. The event to send now, or None.

        - None when MAX_IN_FLIGHT keys are already sending (this endpoint has its share).
        - While parked: None, unless nothing is in flight and now >= probe_at. Then one probe:
          among the first event of each order in the queue, the one with the fewest
          `attempts` (the oldest of those), whatever its retry_at. A fresh event, so that a
          malformed one that fails forever cannot keep the endpoint parked forever.
        - Else the oldest event in `queue` whose order is free: walk the queue keeping a set of
          blocked keys (start with `self.sending`); skip an event whose key is blocked; add its
          key either way (the rest of that order waits behind it); return the first one whose
          `retry_at` (default 0) is <= now.
        - Add the key of the event you return to `self.sending`.
        """
        raise NotImplementedError("TODO stage 2: Endpoint.pick(now)")

    def succeeded(self, ev: Event, now: float) -> None:
        """Stage 2. Delivered: take it off `sending`, `queue` and `retry_at`; failures = 0. If the
        endpoint was parked it is healthy again: unpark it and clear `retry_at`, so the whole
        backlog is replayed now (in order, MAX_IN_FLIGHT at a time)."""
        raise NotImplementedError("TODO stage 2: Endpoint.succeeded(ev, now)")

    def failed(self, ev: Event, now: float) -> bool:
        """Stage 2. The POST failed. Take its key off `sending` and count the failure. After
        DISABLE_AFTER in a row, park the endpoint and probe again at now + PROBE_EVERY. If it is
        not parked and `ev.attempts >= MAX_ATTEMPTS`, the endpoint works but this event does not
        (poison): take it out of the queue and return True (the Dispatcher gives it up).
        Otherwise retry it later, `retry_at[ev.id] = now + backoff(ev.attempts, self.rng)`, and
        return False."""
        raise NotImplementedError("TODO stage 2: Endpoint.failed(ev, now)")


class Dispatcher:
    """Decides what the delivery workers send, and what happens after each answer.

    Contract:
      - `submit(ev, now)` is called once for every new event.
      - `next(now)` is called by a free worker: return the event to POST now, or None (it asks
        again soon). Each event you return is POSTed once, and `done(ev, status, now)` is called
        when it ends: status is the HTTP status, or None (no answer within `timeout`).
      - `timeout` is how long a worker waits for one answer (None: the client's 30 s).
      - Every event must be delivered once, eventually: give one up only if it can never succeed.
    """

    timeout: float | None = None  # Stage 1: ATTEMPT_TIMEOUT

    def __init__(self, give_up: Callable[[Event], None], rng: random.Random | None = None) -> None:
        self.give_up = give_up
        self.rng = rng or random.Random(0)  # for backoff(): runs repeat
        self.queue: deque[Event] = deque()  # one queue for every endpoint
        self.retries: list[tuple[float, int, Event]] = []  # stage 1: (due, id, event), a heap
        self.endpoints: dict[int, Endpoint] = {}  # stage 2: endpoint -> its Endpoint
        self.turn = 0  # stage 2: which endpoint is asked first (round robin)

    def submit(self, ev: Event, now: float) -> None:
        # Stage 2: append it to the queue of its endpoint instead,
        #          self.endpoints.setdefault(ev.endpoint, Endpoint(self.rng)).queue.append(ev)
        #          (create each Endpoint once: setdefault makes one on every call, so test first).
        self.queue.append(ev)

    def next(self, now: float) -> Event | None:
        # Stage 1: a retry that is due goes first: if self.retries and self.retries[0][0] <= now,
        #          return heapq.heappop(self.retries)[2].
        # Stage 2: ask the endpoints in turn, starting at self.turn: return the first event an
        #          Endpoint.pick(now) gives you (and move self.turn past that endpoint, so every
        #          endpoint gets its turn), else None.
        return self.queue.popleft() if self.queue else None

    def done(self, ev: Event, status: int | None, now: float) -> None:
        # Stage 1: on a failure, self.retry(ev, now) instead of giving up.
        # Stage 2: tell its Endpoint: succeeded(ev, now) on ok(status), else failed(ev, now), and
        #          give the event up only when failed() returns True (poison).
        if not ok(status):
            self.give_up(ev)  # fire once: a failed event is gone

    def retry(self, ev: Event, now: float) -> None:
        """Stage 1. Try it again later: push (now + backoff(ev.attempts, self.rng), ev.id, ev)
        onto the self.retries heap (ev.id breaks ties: events do not compare)."""
        raise NotImplementedError("TODO stage 1: Dispatcher.retry(ev, now)")


def backoff(attempt: int, rng: random.Random | None = None) -> float:
    """Stage 1. Seconds to wait after failed attempt number `attempt` (1, 2, 3 ...): "full
    jitter", a random amount between 0 and BACKOFF_BASE doubled for every attempt so far
    (0.5, 1, 2, 4 ... s), at most BACKOFF_CAP. Use `(rng or random).uniform`.

    The jitter matters: when an endpoint comes back, its retries come spread out instead of
    all at once.

    >>> 0 <= backoff(1, random.Random(1)) <= 0.5
    True
    """
    raise NotImplementedError("TODO stage 1: backoff(attempt)")
