"""Lab db_index: YOUR FILE. Edit it and save; the live window reruns it.

A `users` table that keeps growing: ~5 signups/s, plus bulk imports now and then. Users log
in (`find_by_email`, ~30/s) and dashboards ask who signed up in a country in a time range
(`signups_between`). Every row the database reads costs time, and it has only 4 workers.
Right now every query reads the whole table (a full scan), so it gets slower as the table
grows.

Do the stages in order, in this file:

  Stage 1  A hash index for logins: keep a dict email -> position, so `find_by_email`
           reads one row instead of all of them.
  Stage 2  A composite index (country, time) for the ranges: per country, a sorted list
           of (time, position); `signups_between` uses bisect to read only the rows it
           returns. Keep both indexes up to date in `insert` (imports insert old times).

How the storage works (labs/db_index/storage.py):
  pos = self.heap.insert(row)   store a row, get its position
  row = self.heap.get(pos)      read one row (one read)
  self.heap.scan(...)           a full scan: reads every row (what you do now)

Check yourself:  uv run pytest labs/db_index
Peek at a solution (after trying!):  labs/db_index/reference.py
"""

from __future__ import annotations

from bisect import bisect_left, insort  # noqa: F401  (stage 2)

from labs.db_index.storage import Heap, Row


class Table:
    """The users table.

    Contract:
      - `insert(row)` stores a row (rows can arrive with an old `time`: imports).
      - `find_by_email(email)` returns the row with that email, or None.
      - `signups_between(country, start, end)` returns every row of that country with
        start <= time < end, in any order.
    Answers must be right: a wrong answer counts as a failed query.
    """

    def __init__(self, heap: Heap) -> None:
        self.heap = heap
        # Stage 1: a dict email -> position.
        # Stage 2: a dict country -> sorted list of (time, position).

    def insert(self, row: Row) -> None:
        self.heap.insert(row)
        # Stage 1: remember where the row went: pos = self.heap.insert(row), then index it.
        # Stage 2: insort((row.time, pos)) into the country's sorted list.

    def find_by_email(self, email: str) -> Row | None:
        # Stage 1: look the position up in your dict and read just that row: self.heap.get(pos).
        rows = self.heap.scan(email=email)
        return rows[0] if rows else None

    def signups_between(self, country: str, start: float, end: float) -> list[Row]:
        # Stage 2: bisect_left the country's sorted list for (start, -1) and (end, -1),
        # and read only the positions in between.
        return self.heap.scan(country=country, start=start, end=end)
