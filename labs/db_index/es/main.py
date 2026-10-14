"""Laboratorio db_index: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Una tabla `users` que no deja de crecer: ~5 altas/s, y de vez en cuando cargas masivas. Los
usuarios inician sesión (`find_by_email`, ~30/s) y los paneles preguntan quién se dio de alta
en un país en un rango de tiempo (`signups_between`). Cada fila que lee la base de datos
cuesta tiempo, y solo tiene 4 workers. Ahora mismo cada consulta lee la tabla entera (una
lectura completa), así que va más lenta a medida que la tabla crece.

Haz las etapas en orden, en este archivo:

  Etapa 1  Un índice hash para los logins: guarda un dict email -> posición, para que
           `find_by_email` lea una fila en vez de todas.
  Etapa 2  Un índice compuesto (país, tiempo) para los rangos: por país, una lista
           ordenada de (tiempo, posición); `signups_between` usa bisect para leer solo las
           filas que devuelve. Mantén los dos índices al día en `insert` (las cargas
           insertan tiempos antiguos).

Cómo funciona el almacenamiento (labs/db_index/storage.py):
  pos = self.heap.insert(row)   guarda una fila y devuelve su posición
  row = self.heap.get(pos)      lee una fila (una lectura)
  self.heap.scan(...)           una lectura completa: lee todas las filas (lo que haces ahora)

Compruébalo:  LABS_LANG=es uv run pytest labs/db_index
Mira una solución (¡después de intentarlo!):  labs/db_index/es/reference.py
"""

from __future__ import annotations

from bisect import bisect_left, insort  # noqa: F401  (etapa 2)

from labs.db_index.storage import Heap, Row


class Table:
    """La tabla de usuarios.

    Contrato:
      - `insert(row)` guarda una fila (pueden llegar filas con un `time` antiguo: las cargas).
      - `find_by_email(email)` devuelve la fila con ese email, o None.
      - `signups_between(country, start, end)` devuelve cada fila de ese país con
        start <= time < end, en cualquier orden.
    Las respuestas tienen que ser correctas: una respuesta errónea cuenta como consulta fallida.
    """

    def __init__(self, heap: Heap) -> None:
        self.heap = heap
        # Etapa 1: un dict email -> posición.
        # Etapa 2: un dict país -> lista ordenada de (tiempo, posición).

    def insert(self, row: Row) -> None:
        self.heap.insert(row)
        # Etapa 1: apunta dónde quedó la fila: pos = self.heap.insert(row), y después indéxala.
        # Etapa 2: insort((row.time, pos)) en la lista ordenada de su país.

    def find_by_email(self, email: str) -> Row | None:
        # Etapa 1: busca la posición en tu dict y lee solo esa fila: self.heap.get(pos).
        rows = self.heap.scan(email=email)
        return rows[0] if rows else None

    def signups_between(self, country: str, start: float, end: float) -> list[Row]:
        # Etapa 2: bisect_left sobre la lista ordenada del país con (start, -1) y (end, -1),
        # y lee solo las posiciones que quedan entre medias.
        return self.heap.scan(country=country, start=start, end=end)
