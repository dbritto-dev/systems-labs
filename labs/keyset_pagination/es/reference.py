"""Laboratorio keyset_pagination: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import base64
import binascii
import json

from labs.keyset_pagination.api import PAGE_SIZE, BadCursor, Page, Post  # noqa: F401


def encode_cursor(post: Post) -> str:
    # Valores, no un puntero: la página siguiente es "todo lo más viejo que (created_at, id)",
    # exista o no todavía la publicación.
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
            # (created_at, id) es único, así que "más viejo que lo último que vi" nunca salta una
            # publicación que comparte su created_at, ni muestra una dos veces. El índice va directo.
            rows = await self.db.select(PAGE_SIZE, older_than=decode_cursor(cursor))
        return Page(rows, encode_cursor(rows[-1]) if len(rows) == PAGE_SIZE else None)
