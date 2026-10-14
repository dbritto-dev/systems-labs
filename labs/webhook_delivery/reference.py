"""Lab webhook_delivery: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import random
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
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.queue: list[Event] = []  # not delivered yet, oldest first
        self.retry_at: dict[int, float] = {}  # event id -> not before this time
        self.sending: set[int] = set()  # keys with a POST in flight
        self.failures = 0  # in a row
        self.parked = False
        self.probe_at = 0.0

    def pick(self, now: float) -> Event | None:
        if len(self.sending) >= MAX_IN_FLIGHT:
            return None  # this endpoint has its share of the workers
        if self.parked:
            if self.sending or now < self.probe_at:
                return None  # parked: one probe at a time, every PROBE_EVERY seconds
            return self._probe()
        blocked = set(self.sending)
        for ev in self.queue:
            if ev.key in blocked:
                continue  # an earlier event of this order is not delivered yet
            blocked.add(ev.key)  # whatever happens, the rest of this order waits behind it
            if self.retry_at.get(ev.id, 0.0) <= now:
                self.sending.add(ev.key)
                return ev
        return None

    def _probe(self) -> Event | None:
        # The first event of each order is free to go; probe with the one tried least (a fresh one), so
        # a malformed event that fails forever cannot keep the endpoint parked.
        heads: dict[int, Event] = {}
        for ev in self.queue:
            heads.setdefault(ev.key, ev)
        if not heads:
            return None
        ev = min(heads.values(), key=lambda e: e.attempts)  # the oldest among equals
        self.sending.add(ev.key)
        return ev

    def succeeded(self, ev: Event, now: float) -> None:
        self.sending.discard(ev.key)
        self.queue.remove(ev)
        self.retry_at.pop(ev.id, None)
        self.failures = 0
        if self.parked:  # healthy again: replay the backlog now, in order
            self.parked = False
            self.retry_at.clear()

    def failed(self, ev: Event, now: float) -> bool:
        self.sending.discard(ev.key)
        self.failures += 1
        if self.failures >= DISABLE_AFTER:
            self.parked = True
            self.probe_at = now + PROBE_EVERY
        elif ev.attempts >= MAX_ATTEMPTS:  # the endpoint works, this one event does not: poison
            self.queue.remove(ev)
            self.retry_at.pop(ev.id, None)
            return True
        self.retry_at[ev.id] = now + backoff(ev.attempts, self.rng)
        return False


class Dispatcher:
    timeout = ATTEMPT_TIMEOUT

    def __init__(self, give_up: Callable[[Event], None], rng: random.Random | None = None) -> None:
        self.give_up = give_up
        self.rng = rng or random.Random(0)
        self.endpoints: dict[int, Endpoint] = {}
        self.turn = 0  # round robin: which endpoint is asked first

    def submit(self, ev: Event, now: float) -> None:
        ep = self.endpoints.get(ev.endpoint)
        if ep is None:
            ep = self.endpoints[ev.endpoint] = Endpoint(self.rng)
        ep.queue.append(ev)

    def next(self, now: float) -> Event | None:
        eps = list(self.endpoints.values())
        for k in range(len(eps)):
            ev = eps[(self.turn + k) % len(eps)].pick(now)
            if ev is not None:
                self.turn = (self.turn + k + 1) % len(eps)
                return ev
        return None

    def done(self, ev: Event, status: int | None, now: float) -> None:
        ep = self.endpoints[ev.endpoint]
        if ok(status):
            ep.succeeded(ev, now)
        elif ep.failed(ev, now):
            self.give_up(ev)

    # stage 1's retry queue; stage 2 keeps retries per endpoint
    def retry(self, ev: Event, now: float) -> None:
        self.endpoints[ev.endpoint].retry_at[ev.id] = now + backoff(ev.attempts, self.rng)


def backoff(attempt: int, rng: random.Random | None = None) -> float:
    return (rng or random).uniform(0, min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (attempt - 1)))  # full jitter
