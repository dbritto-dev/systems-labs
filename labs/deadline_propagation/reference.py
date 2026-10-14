"""Lab deadline_propagation: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

from core.services import ServiceError
from core.vtime import now

HOP_TIMEOUT = 2.0
MARGIN = 0.2


class DeadlineExceeded(ServiceError):
    """The deadline has passed: nobody is waiting for this answer any more."""


def next_deadline(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return deadline - MARGIN  # the next hop must be done this much before we must


def expired(deadline: float | None, at: float) -> bool:
    return deadline is not None and at >= deadline


async def handle(hop, deadline: float | None) -> str:
    if expired(deadline, now()):  # the caller has already left: do not start the expensive part
        raise DeadlineExceeded(f"{hop.name}: the deadline passed before the work")
    await hop.work()
    if hop.last:
        return "ok"
    child = next_deadline(deadline)
    if child is None:  # nobody told us a deadline: fall back to our own timeout
        return await hop.call_next(None, HOP_TIMEOUT)
    if expired(child, now()):  # no time left for the next service: fail fast, send nothing
        raise DeadlineExceeded(f"{hop.name}: no time left to call the next service")
    return await hop.call_next(child, deadline - now())  # wait as long as our caller does
