"""Laboratorio deadline_propagation: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Una petición pasa por una cadena de cuatro servicios: gateway → api → orders → db
(pasarela, api, pedidos y base de datos). Todos ejecutan el mismo `handle` de abajo:
hacen su propio trabajo mientras ocupan uno de sus trabajadores, y luego llaman al
siguiente servicio y esperan la respuesta. Los usuarios se rinden a los 2 s. Ahora
mismo cada salto espera su propio HOP_TIMEOUT (2 s), contado desde que ÉL llamó, así
que los timeouts no suman lo mismo que el del usuario: un salto que recibió la
petición tarde sigue esperando cuando el usuario ya se fue. Y nadie avisa a la base de
datos: cuando se vuelve lenta (una consulta lenta, contención de bloqueos, una réplica
degradada, una tormenta de GC), se forma una cola delante de sus pocas conexiones, y
ejecuta cada consulta de la cola, también las de usuarios que se fueron hace
segundos. Ese trabajo desperdiciado le quita capacidad a las peticiones vivas, así que
la lentitud empeora.

Haz las etapas en orden, en este archivo:

  Etapa 1  Pasa el plazo hacia abajo: envía al siguiente servicio
           `next_deadline(deadline)` (tu plazo menos MARGIN), y espera solo hasta tu
           propio plazo.
  Etapa 2  Salta el trabajo vencido: antes de tu trabajo y antes de llamar al
           siguiente servicio, si el plazo ya venció, lanza DeadlineExceeded (falla
           rápido: nadie espera la respuesta).

Compruébalo:  LABS_LANG=es uv run pytest labs/deadline_propagation
Mira una solución (¡después de intentarlo!):  labs/deadline_propagation/es/reference.py
"""

from __future__ import annotations

from core.services import ServiceError
from core.vtime import now

HOP_TIMEOUT = 2.0  # segundos que cada salto espera al siguiente, contados desde su propia llamada
MARGIN = 0.2  # segundos que cada salto se reserva: el siguiente debe terminar esto antes que tú


class DeadlineExceeded(ServiceError):
    """El plazo ya pasó: nadie espera esta respuesta."""


def next_deadline(deadline: float | None) -> float | None:
    """Etapa 1. El plazo que envías al siguiente servicio: el tuyo menos MARGIN, para que
    su respuesta (o su error) te llegue mientras quien te llamó aún espera, y para que el
    trabajo que empiece justo antes de su plazo aún pueda terminar antes que el tuyo.
    Sin plazo (None) sigue siendo None."""
    raise NotImplementedError("PENDIENTE etapa 1: next_deadline(deadline)")


def expired(deadline: float | None, at: float) -> bool:
    """Etapa 2. True cuando hay plazo y `at` es igual o posterior a él. Sin plazo (None)
    nunca vence."""
    raise NotImplementedError("PENDIENTE etapa 2: expired(deadline, at)")


async def handle(hop, deadline: float | None) -> str:
    """Cómo atiende cada servicio de la cadena una petición (gateway, api, orders, db).

    Contrato:
      - `deadline` es cuándo deja de esperar quien te llamó (un instante absoluto en el
        reloj de `now()`), o None si no te envió ninguno. La pasarela recibe el del
        usuario: el momento en que se rinde.
      - `hop.name` es "gateway", "api", "orders" o "db"; `hop.last` es True en la db.
      - `await hop.work()` es el trabajo propio de este servicio (en la db: la
        consulta). Es la parte cara, y no se puede parar una vez empezada.
      - `await hop.call_next(deadline, timeout)` envía la petición al siguiente
        servicio con `deadline` (o None) en sus cabeceras, y espera hasta `timeout`
        segundos la respuesta. Lanza ServiceError si la llamada falla o se acaba el
        timeout. El siguiente servicio sigue adelante en cualquier caso: solo conoce el
        plazo que le enviaste.
      - Devuelve "ok"; lanza ServiceError (o DeadlineExceeded) para fallar.
    """
    # Etapa 2: primero, if expired(deadline, now()): raise DeadlineExceeded("...")
    await hop.work()
    if hop.last:
        return "ok"
    # Etapa 1: child = next_deadline(deadline). Si es None, deja la llamada de abajo;
    # si no, envíalo y espera hasta TU plazo:
    #     return await hop.call_next(child, deadline - now())
    # Etapa 2: antes de esa llamada, if expired(child, now()): raise DeadlineExceeded("...")
    return await hop.call_next(None, HOP_TIMEOUT)
