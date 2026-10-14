"""Lab optimistic_locking: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
import random

from labs.optimistic_locking.api import Conflict

MAX_TRIES = 8  # tries per request, the first one included
BASE = 0.005  # seconds; the largest wait after the first conflict
CAP = 0.1  # seconds; no wait is ever longer than this


def backoff(attempt: int, rng: random.Random) -> float:
    # Full jitter: anywhere between 0 and the exponential ceiling, so the requests that lost the
    # same race do not all come back at the same moment and collide again.
    return rng.uniform(0, min(CAP, BASE * 2 ** min(attempt, 30)))


class StockService:
    def __init__(self, db, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random(0)

    async def adjust(self, item: int, delta: int) -> int:
        for attempt in range(MAX_TRIES):
            if attempt:
                await asyncio.sleep(backoff(attempt, self.rng))
            # Read again on every try: the merge is "my change, on top of what is there now".
            row = await self.db.read(item)
            new = row.value + delta
            # The version check and the write are one statement: nobody can write in between.
            if await self.db.compare_and_set(item, new, row.version):
                return new
        raise Conflict(item)
