"""Lab database_index: the storage under your table. It counts every row it reads.

The database keeps rows in a heap: a list, in the order they were inserted. Reading a row
costs time; `reads` counts them, and the scenario turns rows read into query time. Your
indexes (dicts, sorted lists) are free to look up: what costs is going back to the heap.

    pos = heap.insert(row)         store a row, get its position (one write)
    row = heap.get(pos)            read one row by position (one read)
    rows = heap.scan(email=...)    a full scan: reads EVERY row of the table
    rows = heap.scan(country=..., start=..., end=...)   the same, for a time range
    len(heap)                      how many rows the table has

A full scan returns the right rows quickly here (the simulation keeps its own shortcuts),
but it is charged as reading every row, which is what it costs in a real database.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from typing import NamedTuple


class Row(NamedTuple):
    id: int
    email: str
    country: str
    time: float  # when the user signed up, in seconds


class Heap:
    def __init__(self) -> None:
        self._rows: list[Row] = []
        self.reads = 0  # rows read so far
        self.writes = 0
        # The simulation's own shortcuts, so a full scan does not loop in Python.
        # They are not yours to use: reading through them is charged as a full scan.
        self._email: dict[str, int] = {}
        self._country: dict[str, list[tuple[float, int]]] = {}

    def __len__(self) -> int:
        return len(self._rows)

    def insert(self, row: Row) -> int:
        pos = len(self._rows)
        self._rows.append(row)
        self.writes += 1
        self._email[row.email] = pos
        insort(self._country.setdefault(row.country, []), (row.time, pos))
        return pos

    def get(self, pos: int) -> Row:
        self.reads += 1
        return self._rows[pos]

    def scan(self, email: str | None = None, country: str | None = None,
             start: float | None = None, end: float | None = None) -> list[Row]:
        """Every row that matches, by reading the whole table (charged len(self) reads).

        email=...: the rows with that email. country=..., start=..., end=...: the rows of
        that country with start <= time < end.
        """
        self.reads += len(self._rows)
        if email is not None:
            pos = self._email.get(email)
            return [] if pos is None else [self._rows[pos]]
        if country is not None:
            idx = self._country.get(country, [])
            lo = bisect_left(idx, (start if start is not None else float("-inf"), -1))
            hi = bisect_left(idx, (end if end is not None else float("inf"), -1))
            return [self._rows[p] for _, p in idx[lo:hi]]
        return list(self._rows)

    # ---- for the checker: the right answer, without charging anything

    def truth_email(self, email: str) -> int | None:
        return self._email.get(email)

    def truth_range(self, country: str, start: float, end: float) -> int:
        idx = self._country.get(country, [])
        return bisect_left(idx, (end, -1)) - bisect_left(idx, (start, -1))
