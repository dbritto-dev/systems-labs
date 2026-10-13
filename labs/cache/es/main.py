"""Laboratorio cache: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios abren ~200 páginas/s; cada página lee 3 claves con `get()`. Unas pocas
claves son muy calientes. La base de datos tarda 20 ms por lectura y hace 8 a la vez
(unas 400 lecturas/s); por encima de eso las lecturas esperan en una cola. Ahora mismo
`get()` manda cada lectura a la base de datos, así que la cola nunca se vacía.

Haz las etapas en orden, en este archivo:

  Etapa 1  Cache-aside con un TTL: `Cache.lookup`, `Cache.store`, y úsalos en
           `get()`.
  Etapa 2  Protección contra estampidas: cargas single-flight en `get()` (los fallos
           simultáneos de una misma clave comparten una sola lectura de la base de
           datos) y TTL con jitter en `Cache.store` (las claves cargadas juntas no
           caducan juntas).

Compruébalo:  LABS_LANG=es uv run pytest labs/cache
Mira una solución (¡después de intentarlo!):  labs/cache/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.vtime import now


class Cache:
    """Una cache en memoria. El escenario crea una y llama a `clear()` en cada vaciado.

    Contrato:
      - `lookup(key)` devuelve el valor, o None si no está o ya caducó.
      - `store(key, value)` lo guarda `ttl` segundos (`now()` es el reloj).
      - `clear()` lo olvida todo (un despliegue o un reinicio).
    """

    def __init__(self, ttl: float = 30.0, rng: random.Random | None = None) -> None:
        self.ttl = ttl
        self.rng = rng or random.Random(0)
        self.data: dict = {}  # clave -> (valor, caduca en)
        self.loading: dict = {}  # Etapa 2: clave -> future de la carga en curso

    def clear(self) -> None:
        self.data.clear()

    def lookup(self, key):
        # Etapa 1: devuelve el valor si está y now() es anterior a su caducidad.
        raise NotImplementedError("PENDIENTE etapa 1: Cache.lookup")

    def store(self, key, value) -> None:
        # Etapa 1: self.data[key] = (value, now() + self.ttl)
        # Etapa 2: añade jitter al TTL, por ejemplo self.ttl * self.rng.uniform(0.8, 1.2)
        raise NotImplementedError("PENDIENTE etapa 1: Cache.store")


async def get(key, *, cache: Cache, db):
    """Devuelve el valor de `key`. `await db.read(key)` lo carga de la base de datos.

    Etapa 1 (cache-aside): prueba cache.lookup(key); si falla, lee la base de datos,
    guarda el valor con cache.store() y devuélvelo.

    Etapa 2 (single-flight): si ya hay una carga en curso para esta clave
    (cache.loading), espera su future en vez de volver a leer; si no, crea un future
    (asyncio.get_running_loop().create_future()), ponlo en cache.loading, haz la
    lectura, fija su resultado (o su excepción) y quítalo al terminar. Envuelve el
    future compartido en asyncio.shield() cuando lo esperes.
    """
    return await db.read(key)
