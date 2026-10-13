"""Laboratorio circuit_breaker: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Nuestro servicio recibe ~100 peticiones/s con un pool de 24 workers. Cada petición
retiene un worker mientras llama a UNA dependencia a través de tu `Client`:
"payments" (pagos, el 60% de las peticiones) o "recs" (recomendaciones, el 40%). En
momentos al azar una dependencia se vuelve muy lenta (segundos por llamada). Ahora mismo
`Client` espera lo que haga falta, así que las llamadas lentas retienen todos los workers
y las peticiones a la dependencia SANA también fallan: un fallo en cascada.

Haz las etapas en orden, en este archivo:

  Etapa 1  Timeouts: abandona una llamada tras TIMEOUT segundos.
  Etapa 2  Bulkhead: como mucho BULKHEAD_LIMIT llamadas en curso por dependencia;
           más allá, falla al instante, para que una dependencia no se quede con
           todos los workers.
  Etapa 3  Circuit breaker: tras unos cuantos fallos seguidos, deja de llamar a la
           dependencia durante un rato (falla rápido) y luego deja pasar una prueba.

Compruébalo:  LABS_LANG=es uv run pytest labs/circuit_breaker
Mira una solución (¡después de intentarlo!):  labs/circuit_breaker/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.services import ServiceError
from core.vtime import now

TIMEOUT = 1.0  # segundos que puede durar una llamada (las dependencias prometen 1 s)
BULKHEAD_LIMIT = 10  # llamadas en curso por dependencia
FAILURES = 5  # fallos seguidos que abren el breaker
COOLDOWN = 5.0  # segundos que el breaker sigue abierto antes de una prueba


class Client:
    """Llama a una dependencia para una petición de un usuario.

    Contrato:
      - `await client.call(dep)` con dep "payments" o "recs" devuelve lo que devuelve
        la dependencia.
      - Cuando la llamada falla, se agota el tiempo o se rechaza, lanza `ServiceError`.
        Nunca captures otras excepciones: son bugs y deben verse.
      - `self.deps[dep]` es la dependencia: `await self.deps[dep].call(payload)`.

    El servicio crea un solo Client y lo comparten todas las peticiones, así que lo que
    guardes en `self` (bulkheads, breakers) también se comparte.
    """

    def __init__(self, deps: dict, rng: random.Random | None = None) -> None:
        self.deps = deps
        self.rng = rng or random.Random(0)
        # Etapa 2: un Bulkhead(BULKHEAD_LIMIT) por dependencia, por ejemplo en un dict.
        # Etapa 3: un CircuitBreaker() por dependencia.

    async def call(self, dep: str, payload=None):
        # Etapa 1: envuelve la llamada en `async with asyncio.timeout(TIMEOUT):` y convierte
        # el TimeoutError en un ServiceError ("raise ServiceError(...) from None").
        #
        # Etapa 2: antes de llamar, `if not bulkhead.try_enter(): raise ServiceError`;
        # después de la llamada (vaya bien o mal), `bulkhead.leave()` (usa try/finally).
        #
        # Etapa 3: antes de llamar, `if not breaker.allow(): raise ServiceError`;
        # después, `breaker.record_success()` o `breaker.record_failure()`.
        return await self.deps[dep].call(payload)


class Bulkhead:
    """Etapa 2. Como mucho `limit` llamadas en curso; el resto se rechaza al instante.

      try_enter()  si hay menos de `limit` en curso, cuenta una más y devuelve True;
                   si no, devuelve False (no esperes)
      leave()      una llamada terminó
    """

    def __init__(self, limit: int = BULKHEAD_LIMIT) -> None:
        self.limit = limit
        self.in_flight = 0

    def try_enter(self) -> bool:
        raise NotImplementedError("PENDIENTE etapa 2: Bulkhead.try_enter")

    def leave(self) -> None:
        raise NotImplementedError("PENDIENTE etapa 2: Bulkhead.leave")


class CircuitBreaker:
    """Etapa 3. Deja de llamar a una dependencia que no para de fallar.

    Estados:
      "closed"     las llamadas pasan; `failures` fallos seguidos lo abren
      "open"       las llamadas se rechazan al instante, hasta que pasen `cooldown`
                   segundos
      "half-open"  pasa una llamada de prueba: si va bien lo cierra; si falla lo vuelve
                   a abrir (otro `cooldown`)

      allow()           ¿puede pasar esta llamada? (closed: sí; open: no, salvo que el
                        cooldown haya terminado: entonces pasa a half-open y deja pasar UNA)
      record_success()  la llamada funcionó
      record_failure()  la llamada falló o se agotó el tiempo

    Usa `now()` (el reloj de la simulación) para el tiempo.
    """

    def __init__(self, failures: int = FAILURES, cooldown: float = COOLDOWN) -> None:
        self.failures = failures
        self.cooldown = cooldown
        self.state = "closed"
        self.failed = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        raise NotImplementedError("PENDIENTE etapa 3: CircuitBreaker.allow")

    def record_success(self) -> None:
        raise NotImplementedError("PENDIENTE etapa 3: CircuitBreaker.record_success")

    def record_failure(self) -> None:
        raise NotImplementedError("PENDIENTE etapa 3: CircuitBreaker.record_failure")
