"""Lab replication_lag: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import random


class Router:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.written: dict[int, int] = {}  # session -> position of its last write
        self.seen: dict[tuple[int, str], int] = {}  # (session, key) -> newest version it saw

    def wrote(self, session: int, lsn: int) -> None:
        self.written[session] = max(self.written.get(session, 0), lsn)

    def pick(self, session: int, key: str, replicas: list) -> str:
        # Read your writes, and never older than what this session already saw of this key.
        need = max(self.written.get(session, 0), self.seen.get((session, key), 0))
        fresh = [r.name for r in replicas if r.up and r.lsn >= need]
        return self.rng.choice(fresh) if fresh else "primary"

    def saw(self, session: int, key: str, name: str, lsn: int) -> None:
        self.seen[(session, key)] = max(self.seen.get((session, key), 0), lsn)
