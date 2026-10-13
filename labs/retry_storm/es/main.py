"""Laboratorio retry_storm: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios envían ~100 peticiones/s a un servicio a través de `Client`. En momentos al
azar el servicio se cae (falla cada llamada) o falla una parte de sus llamadas. Ahora mismo
`Client` hace una sola llamada y se rinde, así que esas peticiones fallan.

Haz las etapas en orden, en este archivo:

  Etapa 1  Reintentos: reintenta las llamadas fallidas en `Client.call`.
  Etapa 2  Backoff: espera `backoff_delay(attempt)` entre reintentos, y que sea
           exponencial: min(cap, base * 2**attempt).
  Etapa 3  Jitter: que `backoff_delay` sea un número al azar entre 0 y ese backoff
           (jitter completo), para que los usuarios no vuelvan todos a la vez.
  Etapa 4  Presupuesto de reintentos: gasta un token de `RetryBudget` en cada
           reintento, para que los reintentos sumen como mucho ~10% de carga, dure lo
           que dure la caída.

Compruébalo:  LABS_LANG=es uv run pytest labs/retry_storm
Mira una solución (¡después de intentarlo!):  labs/retry_storm/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.services import ServiceError

MAX_RETRIES = 3


class Client:
    """Llama al servicio para una petición de un usuario.

    Contrato:
      - `await client.call(payload)` devuelve lo que devuelve el servicio.
      - Solo `ServiceError` significa "la llamada falló, puedes reintentar".
        Nunca captures otras excepciones: son bugs y deben verse.
      - Cuando se rinde, vuelve a lanzar el último `ServiceError`.

    El escenario crea un solo Client y lo comparten todos los usuarios, así que lo
    que guardes en `self` (como un presupuesto de reintentos) también se comparte.
    """

    def __init__(self, service, rng: random.Random | None = None) -> None:
        self.service = service
        self.rng = rng or random.Random(0)
        # Etapa 4: guarda aquí un RetryBudget y compártelo entre peticiones.

    async def call(self, payload=None):
        # Etapa 1: reintenta ServiceError hasta MAX_RETRIES veces y luego vuelve a
        # lanzar el último error. Pista: un bucle `for attempt in range(MAX_RETRIES + 1):`.
        #
        # Etapa 2: entre intentos, await asyncio.sleep(backoff_delay(attempt, rng=self.rng)).
        #
        # Etapa 4: una vez por petición llama a self.budget.deposit(). Antes de cada
        # reintento, mira primero el número de reintentos y después
        # self.budget.try_withdraw(); si dice que no, vuelve a lanzar el error.
        return await self.service.call(payload)


def backoff_delay(attempt: int, base: float = 0.1, cap: float = 5.0,
                  rng: random.Random | None = None) -> float:
    """Segundos de espera antes del reintento número `attempt` (1 para el primero).

    Etapa 2 (backoff): min(cap, base * 2**attempt), así cada reintento espera el doble.
    Limita también el exponente (por ejemplo min(attempt, 32)) para que un `attempt`
    enorme no desborde.
    Etapa 3 (jitter completo): un número al azar uniforme entre 0 y ese backoff.
    Usa `rng` (un random.Random) si te lo pasan, para que las ejecuciones se repitan.

    >>> 0 <= backoff_delay(1, rng=random.Random(1)) <= 0.2
    True
    """
    raise NotImplementedError("PENDIENTE etapa 2: backoff_delay (backoff exponencial)")


class RetryBudget:
    """Etapa 4. Los reintentos pueden sumar como mucho `ratio` de carga extra (0.1 = 10%).

    Cada petición deposita `ratio` tokens (`deposit()`); cada reintento cuesta un
    token (`try_withdraw()`). Nunca hay más de `max_tokens` tokens, y el presupuesto
    empieza lleno.

      deposit()       suma `ratio` tokens, hasta `max_tokens`
      try_withdraw()  si queda al menos un token, lo gasta y devuelve True;
                      si no, devuelve False (no reintentes)
    """

    def __init__(self, ratio: float = 0.1, max_tokens: float = 10) -> None:
        self.ratio = ratio
        self.max_tokens = max_tokens
        self.tokens = float(max_tokens)

    def deposit(self) -> None:
        raise NotImplementedError("PENDIENTE etapa 4: RetryBudget.deposit")

    def try_withdraw(self) -> bool:
        raise NotImplementedError("PENDIENTE etapa 4: RetryBudget.try_withdraw")
