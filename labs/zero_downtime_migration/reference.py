"""Lab zero_downtime_migration: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio

BATCH = 100
PAUSE = 0.05
LOAD_MAX = 0.60
LAG_MAX = 0.5
GRACE = 1.0


async def read_name(db, m, uid: int):
    return await db.select(uid, m.new if m.read_new else m.old)  # the old column until verified


async def write_name(db, m, uid: int, name) -> None:
    values = {m.new: name}
    if m.write_old:  # old instances still read it (and a rollback can bring them back)
        values[m.old] = name
    await db.update(uid, values)


def busy(db) -> bool:
    return db.load() > LOAD_MAX or db.lag() > LAG_MAX


async def backfill(db, m) -> int:
    copied = 0
    for first in range(0, db.rows, BATCH):
        while busy(db):  # leave the database to the users while it is busy
            await asyncio.sleep(PAUSE)
        copied += await db.copy(m.old, m.new, first, first + BATCH)
        await asyncio.sleep(PAUSE)
    return copied


async def verify(db, m) -> int:
    fixed = 0
    for first in range(0, db.rows, BATCH):
        while busy(db):
            await asyncio.sleep(PAUSE)
        if await db.diff(m.old, m.new, first, first + BATCH):  # an old instance wrote after the copy
            fixed += await db.copy(m.old, m.new, first, first + BATCH)
            await asyncio.sleep(PAUSE)
    return fixed


async def migrate(db, m, fleet) -> None:
    await db.add_column(m.new)  # expand: instant, every row NULL
    await fleet.all_new()  # every instance writes both columns from here on ...
    await backfill(db, m)  # ... so the copy only has to catch up the rows written before
    await fleet.released()  # no rollback can bring old instances back any more
    await verify(db, m)  # re-copy what old instances wrote during a rollback
    m.read_new = True
    m.write_old = False
    await asyncio.sleep(GRACE)  # requests that started before the switch finish
    await db.drop_column(m.old)  # contract
