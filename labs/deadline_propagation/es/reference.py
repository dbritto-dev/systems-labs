"""Laboratorio deadline_propagation: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

from core.services import ServiceError
from core.vtime import now

HOP_TIMEOUT = 2.0
MARGIN = 0.2


class DeadlineExceeded(ServiceError):
    """El plazo ya pasó: nadie espera esta respuesta."""


def next_deadline(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return deadline - MARGIN  # el siguiente salto debe terminar esto antes que nosotros


def expired(deadline: float | None, at: float) -> bool:
    return deadline is not None and at >= deadline


async def handle(hop, deadline: float | None) -> str:
    if expired(deadline, now()):  # quien llamó ya se fue: no empieces la parte cara
        raise DeadlineExceeded(f"{hop.name}: el plazo pasó antes del trabajo")
    await hop.work()
    if hop.last:
        return "ok"
    child = next_deadline(deadline)
    if child is None:  # nadie nos dio un plazo: usamos nuestro propio timeout
        return await hop.call_next(None, HOP_TIMEOUT)
    if expired(child, now()):  # no queda tiempo para el siguiente servicio: falla rápido, no envíes nada
        raise DeadlineExceeded(f"{hop.name}: no queda tiempo para llamar al siguiente servicio")
    return await hop.call_next(child, deadline - now())  # esperamos lo mismo que quien nos llamó
