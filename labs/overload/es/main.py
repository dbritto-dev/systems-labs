"""Laboratorio overload: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un servidor hace ~100 peticiones/s y guarda el resto en una cola. Los usuarios se rinden
con una petición tras 1 s y la vuelven a enviar (como mucho dos veces). En momentos al azar
el tráfico sube de golpe o el servidor pierde capacidad. Ahora mismo la cola no tiene
límite y se atiende por orden de llegada: tras un pico se llena de peticiones de usuarios
que ya se fueron, el servidor dedica todo su tiempo a ellas, y nadie recibe respuesta a
tiempo ni siquiera cuando el pico ya pasó (un fallo metaestable).

`Policy` decide tres cosas. Haz las etapas en orden, en este archivo:

  Etapa 1  Cola con límite: en `admit`, rechaza una petición cuando la cola ya tiene
           MAX_QUEUE. Un rechazo es una respuesta rápida: no hay reintento.
  Etapa 2  Salta lo que llega tarde: en `drop`, devuelve `too_late(request, now)` para que
           el servidor nunca trabaje en una petición cuya respuesta no llegará a tiempo al
           usuario (ya se rindió, o está a punto).
  Etapa 3  LIFO adaptativo: en `newest_first`, devuelve `overloaded(queue_len)` para que
           una cola larga se atienda empezando por lo más nuevo (esos usuarios siguen esperando).

Compruébalo:  LABS_LANG=es uv run pytest labs/overload
Mira una solución (¡después de intentarlo!):  labs/overload/es/reference.py
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_QUEUE = 200  # peticiones que puede tener la cola (2 s de trabajo a 100/s)
USER_TIMEOUT = 1.0  # segundos que un usuario espera una respuesta antes de rendirse
LIFO_AT = 20  # longitud de cola a partir de la cual el servidor está "sobrecargado"
MARGIN = 0.1  # segundos que necesita una respuesta para que valga la pena: el trabajo + la vuelta


@dataclass(slots=True)
class Request:
    """Un intento de un usuario. `sent_at` es cuándo se envió este intento; `attempt` es
    0 para el primer intento, 1 y 2 para los reintentos."""

    id: int
    sent_at: float
    attempt: int = 0


class Policy:
    """Lo que hace el servidor con carga. El escenario crea una y le pregunta:

      admit(request, queue_len, now)  cuando llega una petición: False la rechaza
                                      al momento (el usuario recibe un error, sin reintento)
      drop(request, now)              cuando el servidor va a trabajar en una
                                      petición: True la salta sin coste
      newest_first(queue_len, now)    cuando el servidor elige la siguiente:
                                      True toma la más nueva (LIFO), False la
                                      más antigua (FIFO)
    """

    def admit(self, request: Request, queue_len: int, now: float) -> bool:
        # Etapa 1: return queue_len < MAX_QUEUE
        return True

    def drop(self, request: Request, now: float) -> bool:
        # Etapa 2: return too_late(request, now)
        return False

    def newest_first(self, queue_len: int, now: float) -> bool:
        # Etapa 3: return overloaded(queue_len)
        return False


def too_late(request: Request, now: float) -> bool:
    """Etapa 2. True cuando una respuesta ya no puede llegar a tiempo al usuario: se rinde
    USER_TIMEOUT segundos después de `sent_at`, y queda menos de MARGIN."""
    raise NotImplementedError("PENDIENTE etapa 2: too_late(request, now)")


def overloaded(queue_len: int) -> bool:
    """Etapa 3. True cuando la cola es más larga que LIFO_AT: atiende primero lo más nuevo."""
    raise NotImplementedError("PENDIENTE etapa 3: overloaded(queue_len)")
