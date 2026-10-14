"""Lab deadline_propagation: YOUR FILE. Edit it and save; the live window reruns it.

A request goes through a chain of four services: gateway → api → orders → db.
Every service runs the same `handle` below: it does its own work while holding
one of its workers, then calls the next service and waits for the answer. Users
give up after 2 s. Right now each hop waits its own HOP_TIMEOUT (2 s), counted
from when IT called, so the timeouts do not add up to the user's: a hop that got
the request late keeps waiting after the user has left. And nobody tells the db:
when it slows down (a slow query, lock contention, a degraded replica, a GC
storm), a queue forms in front of its few connections, and it runs every query in
it, also for users who left seconds ago. That wasted work takes the capacity the
live requests need, so the slowdown gets worse.

Do the stages in order, in this file:

  Stage 1  Pass the deadline down: send the next service `next_deadline(deadline)`
           (yours minus MARGIN), and wait only until your own deadline.
  Stage 2  Skip work past the deadline: before your work and before calling the
           next service, if the deadline has expired, raise DeadlineExceeded
           (fail fast: nobody is waiting for the answer).

Check yourself:  uv run pytest labs/deadline_propagation
Peek at a solution (after trying!):  labs/deadline_propagation/reference.py
"""

from __future__ import annotations

from core.services import ServiceError
from core.vtime import now

HOP_TIMEOUT = 2.0  # seconds each hop waits for the next one, counted from its own call
MARGIN = 0.2  # seconds each hop keeps back: the next one must be done this much before you


class DeadlineExceeded(ServiceError):
    """The deadline has passed: nobody is waiting for this answer any more."""


def next_deadline(deadline: float | None) -> float | None:
    """Stage 1. The deadline to send to the next service: yours minus MARGIN, so its
    answer (or its error) reaches you while your caller is still waiting, and work it
    starts just before its deadline can still finish before yours.
    A missing deadline (None) stays None."""
    raise NotImplementedError("TODO stage 1: next_deadline(deadline)")


def expired(deadline: float | None, at: float) -> bool:
    """Stage 2. True when there is a deadline and `at` is at or past it. No deadline
    (None) never expires."""
    raise NotImplementedError("TODO stage 2: expired(deadline, at)")


async def handle(hop, deadline: float | None) -> str:
    """How every service in the chain serves one request (gateway, api, orders, db).

    Contract:
      - `deadline` is when your caller stops waiting (an absolute time on `now()`'s
        clock), or None if it did not send one. The gateway gets the user's: the
        moment they give up.
      - `hop.name` is "gateway", "api", "orders" or "db"; `hop.last` is True at the db.
      - `await hop.work()` is this service's own work (at the db: the query). It is
        the expensive part, and it cannot be stopped once started.
      - `await hop.call_next(deadline, timeout)` sends the request on to the next
        service with `deadline` (or None) in its headers, and waits up to `timeout`
        seconds for the answer. It raises ServiceError if the call fails or the
        timeout passes. The next service carries on either way: all it knows is
        the deadline you sent it.
      - Return "ok"; raise ServiceError (or DeadlineExceeded) to fail.
    """
    # Stage 2: first, if expired(deadline, now()): raise DeadlineExceeded("...")
    await hop.work()
    if hop.last:
        return "ok"
    # Stage 1: child = next_deadline(deadline). If it is None, keep the call below;
    # otherwise send it on and wait until YOUR deadline:
    #     return await hop.call_next(child, deadline - now())
    # Stage 2: before that call, if expired(child, now()): raise DeadlineExceeded("...")
    return await hop.call_next(None, HOP_TIMEOUT)
