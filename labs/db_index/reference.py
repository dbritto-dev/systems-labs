"""Lab db_index: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

from bisect import bisect_left, insort

from labs.db_index.storage import Heap, Row


class Table:
    def __init__(self, heap: Heap) -> None:
        self.heap = heap
        self.by_email: dict[str, int] = {}  # a hash index: email -> position
        self.by_country: dict[str, list[tuple[float, int]]] = {}  # (country, time) -> position

    def insert(self, row: Row) -> None:
        pos = self.heap.insert(row)
        self.by_email[row.email] = pos
        # An import can bring old times, so insert in order rather than append.
        insort(self.by_country.setdefault(row.country, []), (row.time, pos))

    def find_by_email(self, email: str) -> Row | None:
        pos = self.by_email.get(email)
        return None if pos is None else self.heap.get(pos)

    def signups_between(self, country: str, start: float, end: float) -> list[Row]:
        index = self.by_country.get(country, [])
        lo = bisect_left(index, (start, -1))
        hi = bisect_left(index, (end, -1))
        return [self.heap.get(pos) for _, pos in index[lo:hi]]
