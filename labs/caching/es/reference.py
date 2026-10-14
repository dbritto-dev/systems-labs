"""Laboratorio caching: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
import random

from core.vtime import now


class Cache:
    def __init__(self, ttl: float = 30.0, rng: random.Random | None = None) -> None:
        self.ttl = ttl
        self.rng = rng or random.Random(0)
        self.data: dict = {}  # clave -> (valor, caduca en)
        self.loading: dict = {}  # clave -> future de la carga en curso

    def clear(self) -> None:
        self.data.clear()

    def lookup(self, key):
        hit = self.data.get(key)
        if hit is None:
            return None
        value, expires = hit
        if now() >= expires:
            del self.data[key]
            return None
        return value

    def store(self, key, value) -> None:
        # Jitter: las claves cargadas juntas no caducan todas a la vez.
        self.data[key] = (value, now() + self.ttl * self.rng.uniform(0.8, 1.2))


async def get(key, *, cache: Cache, db):
    value = cache.lookup(key)
    if value is not None:
        return value
    pending = cache.loading.get(key)
    if pending is not None:
        # Single-flight: alguien ya está cargando esta clave; espera a esa carga.
        return await asyncio.shield(pending)
    fut = asyncio.get_running_loop().create_future()
    cache.loading[key] = fut
    try:
        value = await db.read(key)
        cache.store(key, value)
        fut.set_result(value)
        return value
    except BaseException as exc:
        fut.set_exception(exc)
        fut.exception()  # márcala como recogida, aunque nadie más la esperara
        raise
    finally:
        del cache.loading[key]
