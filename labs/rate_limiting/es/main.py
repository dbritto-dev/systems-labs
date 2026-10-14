"""Laboratorio rate_limiting: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

20 clientes llaman a una API a través de `RateLimiter`. El backend aguanta 150
peticiones/s; normalmente los clientes envían ~100/s entre todos. En momentos al azar
unos pocos clientes lo inundan a ráfagas. Ahora mismo `RateLimiter` deja pasar todo,
así que el backend se satura y fallan las peticiones de todos los clientes, no solo
las suyas.

Haz las etapas en orden, en este archivo (cada una sustituye la lógica de la anterior):

  Etapa 1  Ventana fija: como mucho `rate` peticiones por cliente en cada ventana de 1 s.
  Etapa 2  Token bucket: por cliente, rellena `rate` tokens por segundo, hasta
           `burst`; cada petición gasta un token.
  Etapa 3  Reparto justo: nunca prometas más de lo que el backend puede hacer. Da a
           cada cliente como mucho min(rate, capacity / clientes activos).

Compruébalo:  LABS_LANG=es uv run pytest labs/rate_limiting
Mira una solución (¡después de intentarlo!):  labs/rate_limiting/es/reference.py
"""

from __future__ import annotations


class RateLimiter:
    """Decide, para cada petición, si puede ir al backend.

    Contrato:
      - `allow(client, now)` devuelve True para dejar pasar la petición, False para
        rechazarla (el cliente recibe un 429 y puede volver a intentarlo más tarde).
      - `client` es un int (0-19); `now` es la hora actual en segundos y solo
        avanza.
      - Debe responder al momento: sin dormir, sin esperar.

    El escenario crea un solo RateLimiter para todos los clientes, así que lo que
    guardes en `self` (contadores, cubos) lo comparten todos.
    """

    def __init__(self, rate: float = 20.0, burst: float = 10.0, capacity: float = 150.0) -> None:
        self.rate = rate  # peticiones por segundo que puede enviar un cliente
        self.burst = burst  # etapa 2: el máximo de tokens que cabe en un cubo
        self.capacity = capacity  # etapa 3: peticiones por segundo que aguanta el backend

    def allow(self, client: int, now: float) -> bool:
        # Etapa 1: lleva una cuenta por (client, int(now)); deja pasar mientras la
        # cuenta sea menor que self.rate. Pista: un dict, y solo importa la ventana actual.
        #
        # Etapa 2: por cliente guarda (tokens, última vez). Rellena
        # (now - last) * self.rate tokens, nunca por encima de self.burst; deja pasar
        # si queda al menos un token, y gástalo. Un cliente nuevo empieza lleno.
        #
        # Etapa 3: recuerda cuándo viste por última vez a cada cliente. Cuenta los
        # clientes vistos en los últimos 2 s, y usa min(self.rate, self.capacity / activos)
        # como ritmo de relleno.
        return True
