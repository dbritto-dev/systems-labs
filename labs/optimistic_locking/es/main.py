"""Laboratorio optimistic_locking: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Tres servidores de aplicación venden del mismo inventario. Cada petición cambia el inventario de
un artículo en `delta` (una venta quita 1-3 unidades, una carga añade algunas): lee la fila, suma
`delta` y escribe el valor nuevo. Ahora mismo gana la última escritura: cuando dos peticiones
leen la misma fila y ambas escriben, la segunda escribe encima de la primera, y ese cambio se
pierde (el inventario queda mal, y nadie se entera).

Haz las etapas en orden, en este archivo:

  Etapa 1  Control de versión: escribe con `compare_and_set(item, new, row.version)` (UPDATE ...
           WHERE version = v). Si no coincide con ninguna fila, alguien la escribió desde que la
           leíste: lanza Conflict(item) (el cliente recibe un 409). Ya no se pierden cambios, pero
           las filas muy usadas fallan mucho.
  Etapa 2  Reintentar tras un conflicto: vuelve a leer la fila y aplica tu cambio al valor nuevo
           (la combinación), hasta MAX_TRIES veces, esperando `backoff(attempt, rng)` entre
           medias: una espera aleatoria pequeña que crece con cada intento, hasta un tope. Lanza
           Conflict solo cuando todos los intentos pierdan. Los usuarios lo consiguen, y sigue
           sin perderse ningún cambio. Por qué esperar: en una oferta los compradores de una
           tanda pulsan juntos y pierden juntos; si reintentan enseguida, vuelven a chocar,
           ronda tras ronda.

Lo que tienes (mira labs/optimistic_locking/api.py):
  row = await self.db.read(item)            row.value, row.version
  await self.db.write(item, value)          gana la última escritura
  await self.db.compare_and_set(item, value, version) -> bool
  Conflict, y self.rng (un random.Random) para el jitter

Un asyncio.Lock no sirve: los otros servidores tienen el suyo.

Compruébalo:  LABS_LANG=es uv run pytest labs/optimistic_locking
Mira una solución (¡después de intentarlo!):  labs/optimistic_locking/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from labs.optimistic_locking.api import Conflict

MAX_TRIES = 8  # etapa 2: intentos por petición, contando el primero
BASE = 0.005  # etapa 2: segundos; la espera más larga tras el primer conflicto
CAP = 0.1  # etapa 2: segundos; ninguna espera dura más que esto


def backoff(attempt: int, rng: random.Random) -> float:
    """Etapa 2. Segundos de espera tras el conflicto número `attempt` (1 tras el primero).

    Contrato:
      - Una espera aleatoria entre 0 y min(CAP, BASE * 2 ** attempt) ("jitter completo").
      - Nunca negativa, nunca mayor que CAP, por grande que sea `attempt`.
      - Usa `rng` (no el módulo `random`), para que una ejecución sea siempre igual.
    """
    # Etapa 2: return rng.uniform(0, min(CAP, BASE * 2 ** attempt)); mantén pequeño el exponente
    #          (min(attempt, 30)) para que nunca desborde.
    raise NotImplementedError("TODO etapa 2: backoff(attempt, rng)")


class StockService:
    """Cambia el inventario de un artículo en `delta`, sin perder el cambio de nadie.

    Contrato:
      - `await service.adjust(item, delta)` devuelve el valor nuevo que escribió.
      - Todo cambio que devuelve tiene que estar en la base de datos: nunca escribas encima de
        un cambio que no leíste.
      - Lanza `Conflict(item)` si te rindes (el cliente recibe un 409).
    """

    def __init__(self, db, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random(0)

    async def adjust(self, item: int, delta: int) -> int:
        # Etapa 1: escribe con `ok = await self.db.compare_and_set(item, new, row.version)`;
        #          si no ok, lanza Conflict(item).
        # Etapa 2: mete la lectura, el cambio y el compare_and_set en un bucle de MAX_TRIES
        #          intentos. Tras un conflicto, `await asyncio.sleep(backoff(attempt, self.rng))`,
        #          y luego lee la fila OTRA VEZ y suma `delta` al valor nuevo. Tras el último
        #          intento, lanza.
        row = await self.db.read(item)
        new = row.value + delta
        await self.db.write(item, new)  # gana la última escritura: lo escrito desde la lectura se pierde
        return new
