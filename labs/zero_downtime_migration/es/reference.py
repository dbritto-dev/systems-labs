"""Laboratorio zero_downtime_migration: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import asyncio

BATCH = 100
PAUSE = 0.05
LOAD_MAX = 0.60
LAG_MAX = 0.5
GRACE = 1.0


async def read_name(db, m, uid: int):
    return await db.select(uid, m.new if m.read_new else m.old)  # la columna vieja hasta verificar


async def write_name(db, m, uid: int, name) -> None:
    values = {m.new: name}
    if m.write_old:  # las instancias viejas aún la leen (y una reversión puede traerlas de vuelta)
        values[m.old] = name
    await db.update(uid, values)


def busy(db) -> bool:
    return db.load() > LOAD_MAX or db.lag() > LAG_MAX


async def backfill(db, m) -> int:
    copied = 0
    for first in range(0, db.rows, BATCH):
        while busy(db):  # deja la base de datos a los usuarios mientras está cargada
            await asyncio.sleep(PAUSE)
        copied += await db.copy(m.old, m.new, first, first + BATCH)
        await asyncio.sleep(PAUSE)
    return copied


async def verify(db, m) -> int:
    fixed = 0
    for first in range(0, db.rows, BATCH):
        while busy(db):
            await asyncio.sleep(PAUSE)
        if await db.diff(m.old, m.new, first, first + BATCH):  # una instancia vieja grabó tras la copia
            fixed += await db.copy(m.old, m.new, first, first + BATCH)
            await asyncio.sleep(PAUSE)
    return fixed


async def migrate(db, m, fleet) -> None:
    await db.add_column(m.new)  # expandir: al instante, cada fila NULL
    await fleet.all_new()  # desde aquí cada instancia graba ambas columnas ...
    await backfill(db, m)  # ... así que la copia solo tiene que ponerse al día con las filas de antes
    await fleet.released()  # ninguna reversión puede traer instancias viejas ya
    await verify(db, m)  # vuelve a copiar lo que grabaron las instancias viejas durante una reversión
    m.read_new = True
    m.write_old = False
    await asyncio.sleep(GRACE)  # terminan las peticiones que empezaron antes del cambio
    await db.drop_column(m.old)  # contraer
