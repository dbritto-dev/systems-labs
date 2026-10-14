"""Lab zero_downtime_migration: YOUR FILE. Edit it and save; the live window reruns it.

The app keeps each user's name in `users.fullname`, and the next release renames it to
`users.display_name` (later releases rename other columns: email → email_address, ...). Six
app instances serve ~100 requests/s while the release rolls out one instance every 2 s, so
for a while OLD instances (they read and write `m.old`) and NEW ones (they run your
`read_name` and `write_name` below) share the database. Your `migrate` runs when the window
opens, 2 s before the deploy starts.

Right now `migrate` renames the column at once: every old instance still running fails on
the column that no longer exists, and a rollback brings failing instances back.

Do the stages in order, in this file:

  Stage 1  Expand/contract: add the new column, write both from the new code, read the old
           one until the new one is filled, and drop the old one only once the release is
           final. Fill it with one copy of every row (`db.copy(m.old, m.new)`).
  Stage 2  Backfill in small batches (BATCH rows, PAUSE between them, wait while busy()),
           and verify() before you switch: re-copy what old instances wrote after the copy.

Check yourself:  uv run pytest labs/zero_downtime_migration
Peek at a solution (after trying!):  labs/zero_downtime_migration/reference.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (stage 1: asyncio.sleep(GRACE))

BATCH = 100  # rows per backfill batch: a copy locks its rows until it commits
PAUSE = 0.05  # seconds between two batches, and between two checks of busy()
LOAD_MAX = 0.60  # the database is busy above this load (0..1) ...
LAG_MAX = 0.5  # ... or while the replica lags more than this many seconds
GRACE = 1.0  # seconds to let requests that started before a switch finish


# ---------------------------------------------------------------- the new release
#
# Every NEW instance runs these for each request. `m` is the migration, shared by every
# instance and your migrate: m.old and m.new are the column names, and two flags that
# migrate can flip at any moment (every new instance sees them at once, like feature flags):
#   m.read_new   False at first: read the old column.
#   m.write_old  True at first: keep writing the old column too.
# `db.select(uid, col)` reads one row's column; `db.update(uid, {col: value, ...})` writes
# them all at once. Either raises if a column does not exist (the request fails).


async def read_name(db, m, uid: int):
    """Return user `uid`'s name.

    Stage 1: read m.new once m.read_new is set, m.old until then (the old column is the one
    every instance keeps up to date).
    """
    return await db.select(uid, m.new)


async def write_name(db, m, uid: int, name) -> None:
    """Set user `uid`'s name.

    Stage 1: write m.new, and m.old too while m.write_old is set, in ONE update, so both
    columns always agree: old instances still read m.old, and a rollback can bring more of
    them back.
    """
    await db.update(uid, {m.new: name})


# ---------------------------------------------------------------- the migration runner


async def migrate(db, m, fleet) -> None:
    """Rename users.<m.old> to users.<m.new> while the release rolls out.

    You have:
      - `await db.add_column(col)`, `await db.drop_column(col)`, `await db.rename_column(a, b)`:
        instant (the rows are not touched).
      - `await db.copy(src, dst, first=0, last=None)`: one UPDATE ... SET dst = src for the
        rows with first <= id < last (every row by default). It takes 0.75 ms a row, locks
        those rows until it commits (writes to them wait) and loads the database meanwhile.
      - `await fleet.all_new()`: waits until every instance runs the new release (a
        rollback can still bring old ones back). `await fleet.released()`: waits until
        the release is final (no rollback any more).

    It must be done (the old column dropped) within 60 s of starting.

    Stage 1 (expand/contract), in this order:
        await db.add_column(m.new)       # expand
        await fleet.all_new()            # from here on every instance writes both columns
        await db.copy(m.old, m.new)      # fill the rows written before (stage 2: backfill)
        await fleet.released()           # no rollback any more
        # stage 2: await verify(db, m) here
        m.read_new = True                # reads move to the new column
        m.write_old = False              # stop writing the old one
        await asyncio.sleep(GRACE)       # requests that started before the switch finish
        await db.drop_column(m.old)      # contract
    """
    await db.rename_column(m.old, m.new)


def busy(db) -> bool:
    """Stage 2. True while the database has no room for the backfill: its load
    (`db.load()`, 0..1) is above LOAD_MAX, or the replica lags (`db.lag()`, seconds) more
    than LAG_MAX. A lagging replica gets taken out of the pool at 2 s, and its reads land on
    the primary."""
    raise NotImplementedError("TODO stage 2: busy(db)")


async def backfill(db, m) -> int:
    """Stage 2. Copy m.old into m.new for every row (ids 0 .. db.rows - 1), BATCH rows per
    `db.copy`, sleeping PAUSE after each batch, and before each batch sleeping PAUSE for as
    long as busy(db). Return how many rows you copied.

    Hint: for first in range(0, db.rows, BATCH): ... db.copy(m.old, m.new, first, first + BATCH)
    """
    raise NotImplementedError("TODO stage 2: backfill(db, m)")


async def verify(db, m) -> int:
    """Stage 2. Find the rows whose two columns differ (an old instance wrote only m.old after
    the copy, during a rollback) and copy them again. Go BATCH rows at a time: count the
    differences with `await db.diff(m.old, m.new, first, last)` (a quick read, no locks) and
    re-copy that batch when it is not 0; wait while busy(db) like backfill. Return the rows
    you re-copied."""
    raise NotImplementedError("TODO stage 2: verify(db, m)")
