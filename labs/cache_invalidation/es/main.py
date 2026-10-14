"""Laboratorio cache_invalidation: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Tres servidores de aplicación muestran fichas de producto (precio, inventario) desde una caché
compartida delante de la base de datos. Las lecturas son muchas; las escrituras llegan de las
compras, de los administradores y de los procesos de carga. Ahora mismo `update` escribe primero la
caché y después la base de datos: cuando la base de datos rechaza la escritura (un timeout de
bloqueo), la caché se queda con un precio que nunca se guardó; cuando dos escrituras se solapan, la
caché acaba con el valor de una y la base de datos con el de la otra. Nada lo arregla hasta que vence
el TTL (5 minutos).

Haz las etapas en orden, en este archivo:

  Etapa 1  Cache-aside: en `update`, escribe primero la base de datos y luego BORRA la clave (no la
           actualices): la siguiente lectura falla y carga el registro nuevo. Se acabaron los precios
           que nunca se guardaron. Pero queda una carrera: una lectura falla, carga el registro VIEJO,
           se detiene (una pausa del recolector, una respuesta lenta) y lo guarda DESPUÉS de que otra
           escritura haya escrito la base de datos y borrado la clave. Esa entrada vieja dura hasta el TTL.
  Etapa 2  Concesiones (leases), como en Facebook: en `read`, pide `cache.lease_get(key)`. Un fallo te
           da un token; carga el registro y guárdalo con `cache.lease_set(key, record, token, TTL)`.
           Un borrado (o un set) de la clave entre medias anula el token, y la caché rechaza el
           relleno tardío y viejo. Deja un TTL corto (30 s) como red de seguridad para lo demás.

Lo que tienes (mira labs/cache_invalidation/api.py):
  record = await self.db.read(key)          await self.db.write(key, record)  (puede lanzar WriteFailed)
  record = await self.cache.get(key)        await self.cache.set(key, record, ttl)
  await self.cache.delete(key)
  lease = await self.cache.lease_get(key)   lease.value (un acierto) o lease.token (un fallo)
  ok = await self.cache.lease_set(key, record, lease.token, ttl)

Un bloqueo dentro de un servidor no sirve: los otros servidores no lo ven.

Compruébalo:  LABS_LANG=es uv run pytest labs/cache_invalidation
Mira una solución (¡después de intentarlo!):  labs/cache_invalidation/es/reference.py
"""

from __future__ import annotations

TTL = 300.0  # segundos que vive un registro en la caché. Etapa 2: hazlo corto (30 s), una red de seguridad


class ProductCache:
    """Lee y escribe registros de producto a través de la caché compartida.

    Contrato:
      - `await read(key)` devuelve el registro del producto: de la caché si está, si no de la base de
        datos (y entonces guárdalo en la caché para los siguientes lectores).
      - `await update(key, record)` guarda el registro; cuando devuelve, toda lectura que empiece
        después debe verlo (o algo más nuevo). Si la base de datos rechaza la escritura, lanza el error.
      - Nunca dejes en la caché un registro más viejo que el de la base de datos (o que nunca se guardó).
    """

    def __init__(self, cache, db) -> None:
        self.cache = cache
        self.db = db

    async def read(self, key: int):
        # Etapa 2: lease = await self.cache.lease_get(key); si lease.value no es None, devuélvelo.
        #          Si no, lee la base de datos y `await self.cache.lease_set(key, record,
        #          lease.token, TTL)`; devuelve el registro tanto si la caché lo aceptó como si no.
        record = await self.cache.get(key)
        if record is not None:
            return record
        record = await self.db.read(key)
        await self.cache.set(key, record, TTL)  # puede llegar después del borrado de otro: viejo hasta el TTL
        return record

    async def update(self, key: int, record) -> None:
        # Etapa 1: escribe primero la base de datos (si lanza un error, la caché queda intacta) y
        #          luego `await self.cache.delete(key)`.
        await self.cache.set(key, record, TTL)  # los lectores ya lo ven...
        await self.db.write(key, record)  # ...pero ¿y si esto falla, o otra escritura se consolida entre medias?
