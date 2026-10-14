"""Laboratorio zero_downtime_migration: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

La app guarda el nombre de cada usuario en `users.fullname`, y la próxima versión lo renombra a
`users.display_name` (las versiones siguientes renombran otras columnas: email →
email_address, ...). Seis instancias de la app atienden ~100 peticiones/s mientras la versión
se despliega, una instancia cada 2 s, así que durante un rato las instancias VIEJAS (leen y
graban `m.old`) y las NUEVAS (ejecutan tus `read_name` y `write_name` de abajo) comparten la
base de datos. Tu `migrate` empieza al abrirse la ventana, 2 s antes que el despliegue.

Ahora mismo `migrate` renombra la columna de golpe: cada instancia vieja que sigue en marcha
falla con la columna que ya no existe, y una reversión trae de vuelta instancias que fallan.

Haz las etapas en orden, en este archivo:

  Etapa 1  Expandir/contraer: añade la columna nueva, graba ambas desde el código nuevo, lee
           la vieja hasta que la nueva esté llena, y borra la vieja solo cuando la versión
           sea definitiva. Llénala con una copia de todas las filas (`db.copy(m.old, m.new)`).
  Etapa 2  Rellena en lotes pequeños (BATCH filas, PAUSE entre ellos, espera mientras
           busy()), y verify() antes de cambiar: vuelve a copiar lo que las instancias viejas
           grabaron después de la copia.

Compruébalo:  LABS_LANG=es uv run pytest labs/zero_downtime_migration
Mira una solución (¡después de intentarlo!):  labs/zero_downtime_migration/es/reference.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (etapa 1: asyncio.sleep(GRACE))

BATCH = 100  # filas por lote del relleno: una copia bloquea sus filas hasta que se consolida
PAUSE = 0.05  # segundos entre dos lotes, y entre dos comprobaciones de busy()
LOAD_MAX = 0.60  # la base de datos está cargada por encima de esta carga (0..1) ...
LAG_MAX = 0.5  # ... o mientras la réplica va más de estos segundos atrasada
GRACE = 1.0  # segundos para que terminen las peticiones que empezaron antes de un cambio


# ---------------------------------------------------------------- la versión nueva
#
# Cada instancia NUEVA ejecuta estas funciones en cada petición. `m` es la migración, compartida
# por todas las instancias y por tu migrate: m.old y m.new son los nombres de las columnas, y dos
# indicadores que migrate puede cambiar en cualquier momento (todas las instancias nuevas lo ven
# a la vez, como opciones de configuración en caliente):
#   m.read_new   False al principio: lee la columna vieja.
#   m.write_old  True al principio: sigue grabando también la columna vieja.
# `db.select(uid, col)` lee la columna de una fila; `db.update(uid, {col: valor, ...})` las graba
# todas a la vez. Las dos lanzan un error si una columna no existe (la petición falla).


async def read_name(db, m, uid: int):
    """Devuelve el nombre del usuario `uid`.

    Etapa 1: lee m.new cuando m.read_new esté activo, y m.old hasta entonces (la columna vieja
    es la que todas las instancias mantienen al día).
    """
    return await db.select(uid, m.new)


async def write_name(db, m, uid: int, name) -> None:
    """Cambia el nombre del usuario `uid`.

    Etapa 1: graba m.new, y también m.old mientras m.write_old esté activo, en UN solo
    update, para que las dos columnas coincidan siempre: las instancias viejas aún leen
    m.old, y una reversión puede traer más de ellas.
    """
    await db.update(uid, {m.new: name})


# ---------------------------------------------------------------- quien ejecuta la migración


async def migrate(db, m, fleet) -> None:
    """Renombra users.<m.old> a users.<m.new> mientras se despliega la versión.

    Tienes:
      - `await db.add_column(col)`, `await db.drop_column(col)`, `await db.rename_column(a, b)`:
        al instante (no tocan las filas).
      - `await db.copy(src, dst, first=0, last=None)`: un UPDATE ... SET dst = src de las filas
        con first <= id < last (todas por defecto). Tarda 0.75 ms por fila, bloquea esas filas
        hasta que se consolida (las escrituras a ellas esperan) y carga la base de datos mientras.
      - `await fleet.all_new()`: espera a que cada instancia ejecute la versión nueva (una
        reversión aún puede traer viejas). `await fleet.released()`: espera a que la versión
        sea definitiva (ya no habrá reversión).

    Debe estar hecha (la columna vieja borrada) antes de 60 s desde que empieza.

    Etapa 1 (expandir/contraer), en este orden:
        await db.add_column(m.new)       # expandir
        await fleet.all_new()            # desde aquí cada instancia graba ambas columnas
        await db.copy(m.old, m.new)      # llena las filas grabadas antes (etapa 2: backfill)
        await fleet.released()           # ya no habrá reversión
        # etapa 2: await verify(db, m) aquí
        m.read_new = True                # las lecturas pasan a la columna nueva
        m.write_old = False              # deja de grabar la vieja
        await asyncio.sleep(GRACE)       # terminan las peticiones que empezaron antes del cambio
        await db.drop_column(m.old)      # contraer
    """
    await db.rename_column(m.old, m.new)


def busy(db) -> bool:
    """Etapa 2. True mientras la base de datos no tiene sitio para el relleno: su carga
    (`db.load()`, 0..1) supera LOAD_MAX, o la réplica va atrasada (`db.lag()`, segundos) más
    de LAG_MAX. Una réplica con 2 s de atraso sale del grupo, y sus lecturas caen en el
    primario."""
    raise NotImplementedError("PENDIENTE etapa 2: busy(db)")


async def backfill(db, m) -> int:
    """Etapa 2. Copia m.old en m.new para todas las filas (ids 0 .. db.rows - 1), BATCH filas
    por `db.copy`, durmiendo PAUSE después de cada lote, y antes de cada lote durmiendo PAUSE
    mientras busy(db). Devuelve cuántas filas copiaste.

    Pista: for first in range(0, db.rows, BATCH): ... db.copy(m.old, m.new, first, first + BATCH)
    """
    raise NotImplementedError("PENDIENTE etapa 2: backfill(db, m)")


async def verify(db, m) -> int:
    """Etapa 2. Encuentra las filas cuyas dos columnas difieren (una instancia vieja grabó solo
    m.old después de la copia, durante una reversión) y vuelve a copiarlas. Ve de BATCH en
    BATCH filas: cuenta las diferencias con `await db.diff(m.old, m.new, first, last)` (una
    lectura rápida, sin bloqueos) y vuelve a copiar ese lote cuando no sea 0; espera mientras
    busy(db) como en backfill. Devuelve las filas que volviste a copiar."""
    raise NotImplementedError("PENDIENTE etapa 2: verify(db, m)")
