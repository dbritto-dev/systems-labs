"""Laboratorio cache_invalidation: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

TTL = 30.0  # corto: una red de seguridad para un borrado que nunca llegó, no la forma de estar al día


class ProductCache:
    def __init__(self, cache, db) -> None:
        self.cache = cache
        self.db = db

    async def read(self, key: int):
        lease = await self.cache.lease_get(key)
        if lease.value is not None:
            return lease.value
        record = await self.db.read(key)
        # La caché lo acepta solo si nadie borró (ni actualizó) la clave desde nuestro fallo: quien
        # escribió después de nuestra lectura la ha borrado, así que este registro es viejo y se rechaza.
        await self.cache.lease_set(key, record, lease.token, TTL)
        return record

    async def update(self, key: int, record) -> None:
        # Primero la base de datos: si la rechaza, la caché nunca vio el registro. Luego borra, nunca
        # actualices: un set compite con otras escrituras; un borrado solo hace que el siguiente lector
        # cargue la verdad.
        await self.db.write(key, record)
        await self.cache.delete(key)
