"""Laboratorio overload: una solución que funciona. Léela después de intentar es/main.py."""

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
        return queue_len < MAX_QUEUE  # descarta carga en la puerta: un "no" rápido vale más que un timeout lento

    def drop(self, request: Request, now: float) -> bool:
        return too_late(request, now)  # nunca gastes trabajo en una respuesta que no llegará a tiempo

    def newest_first(self, queue_len: int, now: float) -> bool:
        return overloaded(queue_len)  # con sobrecarga, las peticiones más nuevas son las que aún se quieren


def too_late(request: Request, now: float) -> bool:
    return request.sent_at + USER_TIMEOUT - now < MARGIN


def overloaded(queue_len: int) -> bool:
    return queue_len > LIFO_AT
