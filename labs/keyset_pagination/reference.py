"""Lab keyset_pagination: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import base64
import binascii
import json

from labs.keyset_pagination.api import PAGE_SIZE, BadCursor, Page, Post  # noqa: F401


def encode_cursor(post: Post) -> str:
    # Values, not a pointer: the page after this post is "everything older than (created_at, id)",
    # whether or not the post itself still exists.
    data = json.dumps({"t": post.created_at, "id": post.id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(data).decode()


def decode_cursor(cursor: str) -> tuple[int, int]:
    try:
        d = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        t, i = d["t"], d["id"]
    except (AttributeError, binascii.Error, ValueError, TypeError, KeyError) as exc:
        raise BadCursor(cursor) from exc
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (t, i)):
        raise BadCursor(cursor)
    return t, i


class FeedAPI:
    def __init__(self, db) -> None:
        self.db = db

    async def list_posts(self, cursor: str | None) -> Page:
        if cursor is None:
            rows = await self.db.select(PAGE_SIZE)
        else:
            # (created_at, id) is unique, so "older than the last post I saw" never skips a post
            # that shares its created_at, and never shows one twice. The index seeks straight there.
            rows = await self.db.select(PAGE_SIZE, older_than=decode_cursor(cursor))
        return Page(rows, encode_cursor(rows[-1]) if len(rows) == PAGE_SIZE else None)
