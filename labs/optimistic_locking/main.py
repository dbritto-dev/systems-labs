"""Lab optimistic_locking: YOUR FILE. Edit it and save; the live window reruns it.

Three app servers sell from the same stock table. Each request changes one item's stock by
`delta` (a sale takes 1-3 units, an import adds some): it reads the row, adds `delta`, and writes
the new value back. Right now the last write wins: when two requests read the same row and both
write, the second one writes over the first, and that update is lost (the stock is wrong, and
nobody is told).

Do the stages in order, in this file:

  Stage 1  Version check: write with `compare_and_set(item, new, row.version)` (UPDATE ... WHERE
           version = v). If it matches no row, someone wrote it since you read it: raise
           Conflict(item) (the client gets a 409). No more lost updates, but busy rows fail a lot.
  Stage 2  Retry on conflict: read the row again and apply your change to the fresh value (the
           merge), up to MAX_TRIES times, sleeping `backoff(attempt, rng)` in between: a small
           random wait that grows with each attempt, up to a cap. Raise Conflict only when every
           try lost. Users succeed, and still no update is lost. Why wait: in a flash sale the
           buyers of one drop click together and lose together; retried at once they collide
           again, round after round.

What you get (see labs/optimistic_locking/api.py):
  row = await self.db.read(item)            row.value, row.version
  await self.db.write(item, value)          last write wins
  await self.db.compare_and_set(item, value, version) -> bool
  Conflict, and self.rng (a random.Random) for the jitter

An asyncio.Lock does not help: the other app servers have their own.

Check yourself:  uv run pytest labs/optimistic_locking
Peek at a solution (after trying!):  labs/optimistic_locking/reference.py
"""

from __future__ import annotations

import asyncio
import random

from labs.optimistic_locking.api import Conflict

MAX_TRIES = 8  # stage 2: tries per request, the first one included
BASE = 0.005  # stage 2: seconds; the largest wait after the first conflict
CAP = 0.1  # stage 2: seconds; no wait is ever longer than this


def backoff(attempt: int, rng: random.Random) -> float:
    """Stage 2. Seconds to wait after conflict number `attempt` (1 after the first conflict).

    Contract:
      - A random wait between 0 and min(CAP, BASE * 2 ** attempt) ("full jitter").
      - Never negative, never above CAP, however large `attempt` is.
      - Use `rng` (not the `random` module), so a run is the same every time.
    """
    # Stage 2: return rng.uniform(0, min(CAP, BASE * 2 ** attempt)); keep the exponent small
    #          (min(attempt, 30)) so it never overflows.
    raise NotImplementedError("TODO stage 2: backoff(attempt, rng)")


class StockService:
    """Changes one item's stock by `delta`, without losing anybody's update.

    Contract:
      - `await service.adjust(item, delta)` returns the new stock value it wrote.
      - Every update that returns must be in the database: never write over a change you did
        not read.
      - Raise `Conflict(item)` if you give up (the client gets a 409).
    """

    def __init__(self, db, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random(0)

    async def adjust(self, item: int, delta: int) -> int:
        # Stage 1: write with `ok = await self.db.compare_and_set(item, new, row.version)`;
        #          if not ok, raise Conflict(item).
        # Stage 2: put the read, the change and the compare_and_set in a loop of MAX_TRIES tries.
        #          On a conflict, `await asyncio.sleep(backoff(attempt, self.rng))`, then read
        #          the row AGAIN and add `delta` to the fresh value. After the last try, raise.
        row = await self.db.read(item)
        new = row.value + delta
        await self.db.write(item, new)  # last write wins: whatever was written since the read is lost
        return new
