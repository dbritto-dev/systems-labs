"""Laboratorio keyset_pagination: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Una API lista un feed: publicaciones, de la más nueva a la más vieja, 20 por página. Los clientes
lo recorren: personas que bajan por él (unas pocas páginas cada una) y procesos de sincronización
que recorren la tabla entera (un indexador de búsqueda, exportaciones). Mientras tanto se siguen
escribiendo publicaciones arriba y borrando en cualquier parte. Ahora mismo una página es
LIMIT 20 OFFSET n, y el cursor es el offset n: cuando se escribe una publicación por encima del
lector, todas las filas bajan un puesto y la página siguiente repite una; cuando se borra una,
otra se salta. Y OFFSET no puede ir directo: la página 1,000 lee 20,020 filas para devolver 20.

Haz las etapas en orden, en este archivo:

  Etapa 1  Clave sobre created_at: el cursor es el created_at de la última publicación de la
           página, y la página siguiente es `select(PAGE_SIZE, older_than=ese)` (WHERE
           created_at < t): el índice va directo, ~20 filas leídas a cualquier profundidad, y lo
           que se escribe o borra en otra parte no lo mueve. Pero muchas publicaciones pueden
           compartir created_at (una carga masiva las marca todas con la misma hora): la página
           siguiente salta todas las de esa hora que no cupieron en esta.
  Etapa 2  Un cursor estable y opaco: (created_at, id) de la última publicación, para que el
           orden sea total (el id desempata), y `older_than=(created_at, id)`. Codifícalo con
           `encode_cursor` (base64 de un JSON pequeño) para que los clientes lo traten como una
           ficha opaca, y léelo con `decode_cursor`, lanzando BadCursor (HTTP 400) para todo lo
           que no sea tuyo. Guarda valores, no un puntero: sigue funcionando aunque se borre la
           publicación de la que salió (nunca vuelvas a buscarla).

Lo que tienes (mira labs/keyset_pagination/api.py):
  rows = await self.db.select(limit, offset=n)            LIMIT limit OFFSET n
  rows = await self.db.select(limit, older_than=t)        WHERE created_at < t
  rows = await self.db.select(limit, older_than=(t, i))   WHERE (created_at, id) < (t, i)
  post = await self.db.get(post_id)                       una publicación por id, None si se borró
  Post(id, created_at), Page(items, next_cursor), BadCursor, PAGE_SIZE

Compruébalo:  LABS_LANG=es uv run pytest labs/keyset_pagination
Mira una solución (¡después de intentarlo!):  labs/keyset_pagination/es/reference.py
"""

from __future__ import annotations

import base64  # noqa: F401  (etapa 2)
import json  # noqa: F401  (etapa 2)

from labs.keyset_pagination.api import PAGE_SIZE, BadCursor, Page, Post  # noqa: F401


def encode_cursor(post: Post) -> str:
    """Etapa 2. El cursor de la página que va después de `post` (la última de una página).

    Contrato:
      - Un texto que guarda post.created_at y post.id, por ejemplo el base64 seguro para URL del
        JSON {"t": created_at, "id": id}. Los clientes no tienen que saber qué lleva dentro.
      - decode_cursor(encode_cursor(post)) == (post.created_at, post.id).
    """
    # Etapa 2: data = json.dumps({"t": post.created_at, "id": post.id}).encode()
    #          return base64.urlsafe_b64encode(data).decode()
    raise NotImplementedError("PENDIENTE etapa 2: encode_cursor(post)")


def decode_cursor(cursor: str) -> tuple[int, int]:
    """Etapa 2. Lee un cursor: (created_at, id).

    Contrato:
      - La inversa de encode_cursor.
      - Cualquier otra cosa (no es base64, no es JSON, faltan claves, valores que no son
        enteros) lanza BadCursor(cursor): el cliente recibe un 400, no un 500 ni otra página.
    """
    # Etapa 2: try: base64.urlsafe_b64decode, json.loads, toma d["t"] y d["id"]; comprueba que
    #          ambos son enteros (isinstance(v, int) and not isinstance(v, bool)); ante cualquier
    #          error, lanza BadCursor.
    raise NotImplementedError("PENDIENTE etapa 2: decode_cursor(cursor)")


class FeedAPI:
    """GET /posts?cursor=...: una página del feed, de la más nueva a la más vieja.

    Contrato:
      - `await api.list_posts(None)` es la primera página; `await api.list_posts(page.next_cursor)`
        la siguiente. Devuelve Page(items, next_cursor); next_cursor es None cuando no queda
        nada más viejo.
      - Un cliente que pagina hasta el final ve exactamente una vez cada publicación que existía
        cuando empezó y no se borró mientras tanto: ninguna saltada, ninguna dos veces.
      - Lee ~una página de filas por página, a cualquier profundidad (el índice, no OFFSET).
    """

    def __init__(self, db) -> None:
        self.db = db

    async def list_posts(self, cursor: str | None) -> Page:
        # Etapa 1: cursor None -> rows = await self.db.select(PAGE_SIZE); si no,
        #          rows = await self.db.select(PAGE_SIZE, older_than=int(cursor)).
        #          next_cursor = str(rows[-1].created_at) si hay filas.
        # Etapa 2: older_than=decode_cursor(cursor), y next_cursor = encode_cursor(rows[-1]).
        offset = int(cursor) if cursor else 0
        rows = await self.db.select(PAGE_SIZE, offset=offset)  # lee offset + 20 filas
        more = len(rows) == PAGE_SIZE
        return Page(rows, str(offset + PAGE_SIZE) if more else None)  # la siguiente: 20 filas más abajo
