"""Lab keyset_pagination: YOUR FILE. Edit it and save; the live window reruns it.

An API lists a feed: posts, newest first, 20 to a page. Clients page through it: people
scrolling (a few pages each), and sync jobs that walk the whole table (a search indexer, exports).
Meanwhile posts keep being written at the top and deleted anywhere. Right now a page is
LIMIT 20 OFFSET n, and the cursor is the offset: when a post is written above the reader, every
row shifts down one place and the next page repeats a post; when one is deleted, a post is
skipped. And OFFSET cannot seek: page 1,000 reads 20,020 rows to return 20.

Do the stages in order, in this file:

  Stage 1  Keyset on created_at: the cursor is the created_at of the last post on the page, and
           the next page is `select(PAGE_SIZE, older_than=that)` (WHERE created_at < t): an
           index seek, ~20 rows read however deep, and inserts or deletes elsewhere do not move
           it. But many posts can share one created_at (a bulk import stamps them all with one
           time): the next page jumps past every post of that time that did not fit on this one.
  Stage 2  A stable, opaque cursor: (created_at, id) of the last post, so the order is total
           (id breaks the ties), and `older_than=(created_at, id)`. Encode it with
           `encode_cursor` (base64 of a little JSON) so clients treat it as an opaque token, and
           read it back with `decode_cursor`, raising BadCursor (HTTP 400) for anything that is
           not one of yours. It holds values, not a pointer: it keeps working after the post it
           came from is deleted (never look the post up again).

What you get (see labs/keyset_pagination/api.py):
  rows = await self.db.select(limit, offset=n)            LIMIT limit OFFSET n
  rows = await self.db.select(limit, older_than=t)        WHERE created_at < t
  rows = await self.db.select(limit, older_than=(t, i))   WHERE (created_at, id) < (t, i)
  post = await self.db.get(post_id)                       one post by id, None if deleted
  Post(id, created_at), Page(items, next_cursor), BadCursor, PAGE_SIZE

Check yourself:  uv run pytest labs/keyset_pagination
Peek at a solution (after trying!):  labs/keyset_pagination/reference.py
"""

from __future__ import annotations

import base64  # noqa: F401  (stage 2)
import json  # noqa: F401  (stage 2)

from labs.keyset_pagination.api import PAGE_SIZE, BadCursor, Page, Post  # noqa: F401


def encode_cursor(post: Post) -> str:
    """Stage 2. The cursor for the page after `post` (the last post of a page).

    Contract:
      - A string that holds post.created_at and post.id, e.g. the URL-safe base64 of the JSON
        {"t": created_at, "id": id}. Clients must not need to know what is inside.
      - decode_cursor(encode_cursor(post)) == (post.created_at, post.id).
    """
    # Stage 2: data = json.dumps({"t": post.created_at, "id": post.id}).encode()
    #          return base64.urlsafe_b64encode(data).decode()
    raise NotImplementedError("TODO stage 2: encode_cursor(post)")


def decode_cursor(cursor: str) -> tuple[int, int]:
    """Stage 2. Read a cursor back: (created_at, id).

    Contract:
      - The inverse of encode_cursor.
      - Anything else (not base64, not JSON, missing keys, values that are not ints) raises
        BadCursor(cursor): the client gets a 400, not a 500 and not some other page.
    """
    # Stage 2: try: base64.urlsafe_b64decode, json.loads, take d["t"] and d["id"]; check both are
    #          ints (isinstance(v, int) and not isinstance(v, bool)); on any error raise BadCursor.
    raise NotImplementedError("TODO stage 2: decode_cursor(cursor)")


class FeedAPI:
    """GET /posts?cursor=...: one page of the feed, newest first.

    Contract:
      - `await api.list_posts(None)` is the first page; `await api.list_posts(page.next_cursor)`
        the next one. Return Page(items, next_cursor); next_cursor is None when there is nothing
        older.
      - A client that pages to the end sees every post that existed when it started and was not
        deleted meanwhile exactly once: none skipped, none twice.
      - Read ~one page of rows per page, however deep (an index seek, not OFFSET).
    """

    def __init__(self, db) -> None:
        self.db = db

    async def list_posts(self, cursor: str | None) -> Page:
        # Stage 1: cursor None -> rows = await self.db.select(PAGE_SIZE); else
        #          rows = await self.db.select(PAGE_SIZE, older_than=int(cursor)).
        #          next_cursor = str(rows[-1].created_at) if there are rows.
        # Stage 2: older_than=decode_cursor(cursor), and next_cursor = encode_cursor(rows[-1]).
        offset = int(cursor) if cursor else 0
        rows = await self.db.select(PAGE_SIZE, offset=offset)  # reads offset + 20 rows
        more = len(rows) == PAGE_SIZE
        return Page(rows, str(offset + PAGE_SIZE) if more else None)  # the next page: 20 rows further down
