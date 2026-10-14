"""What your FeedAPI gets: a database of posts, read newest first, and the shapes of an answer.

    rows = await db.select(limit)                  SELECT id, created_at FROM posts
                                                   ORDER BY created_at DESC, id DESC LIMIT limit
    rows = await db.select(limit, offset=n)        ... LIMIT limit OFFSET n
    rows = await db.select(limit, older_than=t)    ... WHERE created_at < t ORDER BY ... LIMIT limit
    rows = await db.select(limit, older_than=(t, i))
                                                   ... WHERE (created_at, id) < (t, i) ORDER BY ... LIMIT limit
    post = await db.get(post_id)                   SELECT ... WHERE id = post_id   (None if it is gone)

    Post(id, created_at)                           created_at in whole milliseconds since 1970
    Page(items, next_cursor)                       what list_posts returns; next_cursor None at the end
    raise BadCursor(cursor)                        the client sent a cursor you cannot read (HTTP 400)

There is an index on (created_at, id), so `older_than` seeks straight to its place and reads only
the rows it returns. OFFSET cannot seek: the database walks the index from the top and throws
away the first n rows, so it reads n + limit rows. Each row read costs the database time (10 us),
and it runs only 4 queries at once: the rest wait their turn.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_left, insort
from contextvars import ContextVar
from typing import NamedTuple

from core.vtime import now

PAGE_SIZE = 20  # posts per page
WORKERS = 4  # queries the database runs at once
ROW_COST = 1e-5  # seconds of database time per row read
OVERHEAD = 5e-4  # seconds of database time per query, whatever it reads
LATENCY = 0.002  # one round trip between the API and the database
EPOCH_MS = 1_760_000_000_000  # created_at of virtual time 0:00 (an ordinary Unix time in ms)

# The page being served: the scenario sets a dict, the database adds the rows it reads to it.
current_page: ContextVar[dict | None] = ContextVar("current_page", default=None)


class Post(NamedTuple):
    id: int
    created_at: int  # milliseconds since 1970; many posts can share one


class Page(NamedTuple):
    items: list[Post]  # newest first
    next_cursor: str | None  # what the client sends to get the next page; None: no more pages


class BadCursor(Exception):
    """The cursor the client sent cannot be read (garbage, edited, or from somewhere else): HTTP 400."""


def created_ms(t: float) -> int:
    """The created_at a post written at virtual time t gets."""
    return EPOCH_MS + int(t * 1000)


def _bound(older_than) -> tuple:
    """The key to bisect for: rows strictly below it are older."""
    if isinstance(older_than, int) and not isinstance(older_than, bool):
        return (older_than,)  # (t,) sorts before every (t, id): WHERE created_at < t
    if (isinstance(older_than, (tuple, list)) and len(older_than) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in older_than)):
        return (older_than[0], older_than[1])  # WHERE (created_at, id) < (t, id)
    raise TypeError(f"older_than must be a created_at (int) or a (created_at, id) pair of ints, "
                    f"not {older_than!r}")


class Database:
    """The posts table, an index on (created_at, id), and 4 workers that run queries in turn.

    A query is answered from the table as it is when it arrives; then it waits for a worker and
    holds it for OVERHEAD + rows read * ROW_COST seconds. Queries that arrive while every worker
    is busy queue (first come, first served), so one slow query makes everyone behind it wait.
    """

    def __init__(self, posts: list[Post] = (), workers: int = WORKERS, latency: float = LATENCY) -> None:
        self.latency = latency
        self._keys: list[tuple[int, int]] = sorted((p.created_at, p.id) for p in posts)  # oldest first
        self._at: dict[int, int] = {p.id: p.created_at for p in posts}
        self._free = [0.0] * workers  # when each worker is free again
        self.busy: list[tuple] = []  # (start, end, rows read, worker, page id): for the pictures

    # ---- what your code calls

    async def select(self, limit: int, *, offset: int = 0, older_than=None) -> list[Post]:
        if not isinstance(limit, int) or limit < 0 or not isinstance(offset, int) or offset < 0:
            raise ValueError(f"limit and offset must be ints >= 0, not {limit!r} and {offset!r}")
        keys = self._keys
        hi = len(keys) if older_than is None else bisect_left(keys, _bound(older_than))
        end = hi - offset  # newest first: row k from the top is keys[hi - 1 - k]
        rows = [Post(i, c) for c, i in reversed(keys[max(0, end - limit):max(0, end)])]
        read = min(hi, offset + limit)  # OFFSET walks past every row it skips
        await self._run(read)
        return rows

    async def get(self, post_id: int) -> Post | None:
        created = self._at.get(post_id)
        await self._run(1)
        return None if created is None else Post(post_id, created)

    async def _run(self, read: int) -> None:
        page = current_page.get()
        if page is not None:
            page["read"] += read
            page["queries"] += 1
        arrive = now() + self.latency / 2
        k = min(range(len(self._free)), key=self._free.__getitem__)
        start = max(arrive, self._free[k])
        end = self._free[k] = start + OVERHEAD + read * ROW_COST
        self.busy.append((start, end, read, k, page["id"] if page is not None else -1))
        await asyncio.sleep(end + self.latency / 2 - now())

    # ---- what the rest of the app does (not your code)

    def insert(self, post: Post) -> None:
        insort(self._keys, (post.created_at, post.id))
        self._at[post.id] = post.created_at

    def delete(self, post_id: int) -> bool:
        created = self._at.pop(post_id, None)
        if created is None:
            return False
        i = bisect_left(self._keys, (created, post_id))
        del self._keys[i]
        return True

    def newest(self, n: int) -> list[tuple[int, int]]:
        """The newest n (created_at, id) keys, oldest first (for the scenario)."""
        return self._keys[-n:]

    def __len__(self) -> int:
        return len(self._keys)
