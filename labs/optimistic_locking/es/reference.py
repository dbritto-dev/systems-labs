"""Laboratorio optimistic_locking: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
import random

from labs.optimistic_locking.api import Conflict

MAX_TRIES = 8  # intentos por petición, contando el primero
BASE = 0.005  # segundos; la espera más larga tras el primer conflicto
CAP = 0.1  # segundos; ninguna espera dura más que esto


def backoff(attempt: int, rng: random.Random) -> float:
    # Jitter completo: cualquier valor entre 0 y el techo exponencial, para que las peticiones que
    # perdieron la misma carrera no vuelvan todas en el mismo instante y choquen otra vez.
    return rng.uniform(0, min(CAP, BASE * 2 ** min(attempt, 30)))


class StockService:
    def __init__(self, db, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random(0)

    async def adjust(self, item: int, delta: int) -> int:
        for attempt in range(MAX_TRIES):
            if attempt:
                await asyncio.sleep(backoff(attempt, self.rng))
            # Vuelve a leer en cada intento: la combinación es "mi cambio, encima de lo que hay ahora".
            row = await self.db.read(item)
            new = row.value + delta
            # La comprobación de versión y la escritura son una sola sentencia: nadie escribe entre medias.
            if await self.db.compare_and_set(item, new, row.version):
                return new
        raise Conflict(item)
