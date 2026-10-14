"""Laboratorio connection_pool: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
from collections import deque


class PoolTimeout(Exception):
    """No se liberó ninguna conexión dentro del timeout del pool."""


class Pool:
    def __init__(self, db, max_size: int = 20, timeout: float = 0.5) -> None:
        self.db = db
        self.max_size = max_size
        self.timeout = timeout
        self.idle: list = []  # conexiones abiertas que nadie está usando
        self.size = 0  # conexiones abiertas, libres o en uso
        self.waiters: deque[asyncio.Future] = deque()  # peticiones esperando una conexión, la más antigua primero

    async def acquire(self):
        if self.idle:
            return self.idle.pop()
        if self.size < self.max_size:
            self.size += 1
            try:
                return await self.db.connect()
            except BaseException:
                self.size -= 1
                raise
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append(fut)
        try:
            async with asyncio.timeout(self.timeout):
                return await fut
        except TimeoutError:
            if fut.done() and not fut.cancelled():  # le dieron una conexión justo cuando se acababa el tiempo
                return fut.result()
            raise PoolTimeout(f"ninguna conexión libre tras {self.timeout:.1f} s") from None

    def release(self, conn) -> None:
        while self.waiters:  # dásela directamente a la petición más antigua que siga esperando
            fut = self.waiters.popleft()
            if not fut.done():
                fut.set_result(conn)
                return
        self.idle.append(conn)
