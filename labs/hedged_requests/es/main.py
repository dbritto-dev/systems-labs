"""Laboratorio hedged_requests: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios envían ~100 lecturas/s a través de tu `Client`. Cada clave está en 3
réplicas, y cualquiera puede responder. Las respuestas tardan ~10 ms, pero más o menos
1 de cada 50 tarda 100-400 ms (una pausa de GC, un fallo de caché, un disco lento): esa
respuesta lenta y rara es la que ve el usuario del p99. En momentos al azar una réplica
se vuelve mucho más lenta durante un rato (una compactación, un vecino ruidoso, un
volumen degradado), o se vuelven lentas todas. Ahora mismo `Client` pregunta a una
réplica y espera lo que haga falta.

Haz las etapas en orden, en este archivo:

  Etapa 1  Copia: si la primera réplica no ha respondido tras HEDGE_AFTER segundos
           (más o menos el p95 de una respuesta), manda una copia de la lectura a
           otra réplica y devuelve la que responda antes.
  Etapa 2  Presupuesto y cancelación: gasta un token de `HedgeBudget` por cada copia,
           para que las copias añadan ~5% de carga como mucho por lento que vaya todo,
           y cancela la llamada que perdió la carrera (nadie necesita su respuesta).

Compruébalo:  LABS_LANG=es uv run pytest labs/hedged_requests
Mira una solución (¡después de intentarlo!):  labs/hedged_requests/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

HEDGE_AFTER = 0.020  # segundos sin respuesta antes de mandar una copia (~p95 de una respuesta)


class Client:
    """Lee una clave para la petición de un usuario, de cualquiera de las réplicas.

    Contrato:
      - `await client.read(key)` devuelve el valor que devuelve una réplica.
      - `self.replicas` es la lista de réplicas; `await replica.get(key)` le pregunta a una.
        Todas las réplicas tienen todas las claves, así que cualquier respuesta es la buena.
      - Pregunta a cada réplica una vez como mucho por lectura.

    El escenario crea un solo Client y lo comparten todos los usuarios, así que lo que
    guardes en `self` (como un presupuesto de copias) también se comparte.
    """

    def __init__(self, replicas: list, rng: random.Random | None = None) -> None:
        self.replicas = replicas
        self.rng = rng or random.Random(0)
        # Etapa 2: guarda aquí un HedgeBudget y compártelo entre lecturas.

    async def read(self, key):
        # Etapa 1: elige dos réplicas distintas (`self.rng.sample(self.replicas, 2)`).
        # Arranca la primera llamada como tarea (`asyncio.ensure_future(first.get(key))`)
        # y espérala, HEDGE_AFTER como mucho:
        #     done, _ = await asyncio.wait(calls, timeout=HEDGE_AFTER)
        # Si no ha terminado, arranca la copia en la segunda réplica y espera a la que
        # termine antes:
        #     done, _ = await asyncio.wait(calls, return_when=asyncio.FIRST_COMPLETED)
        # y devuelve `done.pop().result()`.
        #
        # Etapa 2: una vez por lectura llama a self.budget.deposit(); manda la copia solo
        # si self.budget.try_withdraw() dice que sí (si no, sigue esperando a la primera).
        # Antes de devolver, cancela cada llamada que siga en curso (`task.cancel()`):
        # ponlo en un `finally:`, para que también pase cuando el usuario se rinde.
        replica = self.rng.choice(self.replicas)
        return await replica.get(key)


class HedgeBudget:
    """Etapa 2. Las copias pueden añadir como mucho `ratio` de carga extra (0.05 = 5%).

    Cada lectura deposita `ratio` tokens (`deposit()`); cada copia cuesta un token
    (`try_withdraw()`). Los tokens nunca pasan de `max_tokens`, y el presupuesto
    empieza lleno.

      deposit()       suma `ratio` tokens, hasta `max_tokens`
      try_withdraw()  si queda al menos un token, tómalo y devuelve True; si no,
                      devuelve False (no mandes la copia)
    """

    def __init__(self, ratio: float = 0.05, max_tokens: float = 10) -> None:
        self.ratio = ratio
        self.max_tokens = max_tokens
        self.tokens = float(max_tokens)

    def deposit(self) -> None:
        raise NotImplementedError("TODO etapa 2: HedgeBudget.deposit")

    def try_withdraw(self) -> bool:
        raise NotImplementedError("TODO etapa 2: HedgeBudget.try_withdraw")
