"""Laboratorio conn_pool: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios envían ~100 peticiones/s. Cada petición le pide a tu `Pool` una conexión a
la base de datos (`acquire()`), ejecuta una consulta y la devuelve (`release()`). Abrir
una conexión es lento (~40 ms) y una consulta es rápida (~8 ms). La base de datos admite
como mucho 50 conexiones abiertas y va más lenta cuando más de ~20 trabajan a la vez.
Ahora mismo cada petición abre una conexión nueva y la cierra al terminar.

Haz las etapas en orden, en este archivo:

  Etapa 1  Reutiliza: guarda las conexiones liberadas en el pool y vuelve a darlas.
  Etapa 2  Pon tope: nunca abras más de `max_size` conexiones; si están todas
           ocupadas, espera a que se libere una.
  Etapa 3  Timeout: espera como mucho `timeout` segundos por una conexión y luego
           lanza PoolTimeout (falla rápido en vez de amontonarte).

Compruébalo:  LABS_LANG=es uv run pytest labs/conn_pool
Mira una solución (¡después de intentarlo!):  labs/conn_pool/es/reference.py
"""

from __future__ import annotations

import asyncio
from collections import deque


class PoolTimeout(Exception):
    """Etapa 3. La lanza acquire() si no se libera ninguna conexión en `timeout` segundos."""


class Pool:
    """Reparte conexiones a la base de datos.

    Contrato:
      - `await pool.acquire()` devuelve una conexión abierta (de `await self.db.connect()`,
        que puede lanzar TooManyConnections si la base de datos ya tiene 50 abiertas).
      - `pool.release(conn)` se llama cuando la petición ya no la necesita.
      - `conn.close()` cierra una conexión (y la base de datos puede aceptar otra).

    El escenario crea un solo Pool para todos los usuarios, así que lo que guardes en
    `self` se comparte.
    """

    def __init__(self, db, max_size: int = 20, timeout: float = 0.5) -> None:
        self.db = db
        self.max_size = max_size
        self.timeout = timeout
        self.idle: list = []  # Etapa 1: conexiones abiertas que nadie está usando
        self.size = 0  # Etapa 2: conexiones abiertas, libres o en uso
        self.waiters: deque[asyncio.Future] = deque()  # Etapa 2: peticiones esperando, la más antigua primero

    async def acquire(self):
        # Etapa 1: si hay una conexión libre, dásela en vez de conectar.
        #
        # Etapa 2: conecta solo mientras self.size < self.max_size (cuéntala en self.size);
        # si no, espera a que se libere una: `return await self._wait_for_release()`.
        return await self.db.connect()

    def release(self, conn) -> None:
        # Etapa 1: guarda la conexión (self.idle.append(conn)) en vez de cerrarla.
        #
        # Etapa 2: si hay una petición esperando, dale la conexión directamente a la más
        # antigua (fut.set_result(conn)) en vez de devolverla a self.idle.
        conn.close()

    async def _wait_for_release(self):
        """Espera a que release() le dé una conexión a esta petición, y devuélvela.

        Etapa 2: crea un future (asyncio.get_running_loop().create_future()), añádelo a
        self.waiters y espéralo con await.
        Etapa 3: espera como mucho self.timeout segundos (async with asyncio.timeout(...))
        y luego lanza PoolTimeout. Cuidado: si el future recibió una conexión justo cuando
        se acababa el tiempo (fut.done() y no fut.cancelled()), devuelve fut.result() en
        vez de perderla.
        """
        raise NotImplementedError("PENDIENTE etapa 2: espera una conexión liberada")
