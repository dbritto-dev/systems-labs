"""What your Dispatcher gets: the events to deliver, and what each attempt answered.

    ev.id                 unique, in the order events were made
    ev.endpoint           which customer endpoint it goes to: 0 .. ENDPOINTS-1
    ev.key, ev.seq        the order it is about, and its place in that order's story:
                          1 order.created, 2 order.paid, 3 order.fulfilled, 4 order.refunded
    ev.type, ev.created   its name, and when it was made
    ev.attempts           attempts so far, counted by the platform (1 during the first)
    ok(status)            True for a 2xx answer; status is the HTTP status, or None when there
                          was no answer at all (refused, a TLS error, or the timeout ran out)
    give_up(ev)           mark it failed for good: it is never delivered (the customer can
                          only replay it by hand from their dashboard)

The platform has WORKERS delivery workers. A free worker asks your `next(now)` what to send,
POSTs it (waiting at most `Dispatcher.timeout` seconds, CLIENT_TIMEOUT when that is None) and
reports back with `done(ev, status, now)`. Your code never waits: it only decides.
"""

from __future__ import annotations

from dataclasses import dataclass

WORKERS = 24  # delivery workers: at most this many POSTs in flight, for every endpoint together
ENDPOINTS = 20  # customer endpoints
CLIENT_TIMEOUT = 30.0  # seconds the HTTP client waits for an answer when you set no timeout

TYPES = ("order.created", "order.paid", "order.fulfilled", "order.refunded")


@dataclass(slots=True, eq=False)
class Event:
    """One webhook event for one customer endpoint."""

    id: int
    endpoint: int
    key: int  # the order it is about
    seq: int  # 1, 2, 3, 4: the order the customer must see this order's events in
    type: str
    created: float
    attempts: int = 0  # counted by the platform: do not change it


def ok(status: int | None) -> bool:
    """A 2xx answer: the endpoint has the event."""
    return status is not None and 200 <= status < 300
