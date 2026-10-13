"""Lab overload: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

from dataclasses import dataclass

MAX_QUEUE = 200
USER_TIMEOUT = 1.0
LIFO_AT = 20
MARGIN = 0.1


@dataclass(slots=True)
class Request:
    id: int
    sent_at: float
    attempt: int = 0


class Policy:
    def admit(self, request: Request, queue_len: int, now: float) -> bool:
        return queue_len < MAX_QUEUE  # shed load at the door: a fast "no" beats a slow timeout

    def drop(self, request: Request, now: float) -> bool:
        return too_late(request, now)  # never spend work on a reply that cannot arrive in time

    def newest_first(self, queue_len: int, now: float) -> bool:
        return overloaded(queue_len)  # under overload, the newest requests are the ones still wanted


def too_late(request: Request, now: float) -> bool:
    return request.sent_at + USER_TIMEOUT - now < MARGIN


def overloaded(queue_len: int) -> bool:
    return queue_len > LIFO_AT
