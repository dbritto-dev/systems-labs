"""Laboratorio database_index: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

from bisect import bisect_left, insort

from labs.database_index.storage import Heap, Row


class Table:
    def __init__(self, heap: Heap) -> None:
        self.heap = heap
        self.by_email: dict[str, int] = {}  # un índice hash: email -> posición
        self.by_country: dict[str, list[tuple[float, int]]] = {}  # (país, tiempo) -> posición

    def insert(self, row: Row) -> None:
        pos = self.heap.insert(row)
        self.by_email[row.email] = pos
        # Una carga puede traer tiempos antiguos: inserta en orden en vez de añadir al final.
        insort(self.by_country.setdefault(row.country, []), (row.time, pos))

    def find_by_email(self, email: str) -> Row | None:
        pos = self.by_email.get(email)
        return None if pos is None else self.heap.get(pos)

    def signups_between(self, country: str, start: float, end: float) -> list[Row]:
        index = self.by_country.get(country, [])
        lo = bisect_left(index, (start, -1))
        hi = bisect_left(index, (end, -1))
        return [self.heap.get(pos) for _, pos in index[lo:hi]]
