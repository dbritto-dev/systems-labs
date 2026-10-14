"""Lab load_balancing: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import random


class Balancer:
    def __init__(self, servers: int, rng: random.Random) -> None:
        self.servers = servers
        self.rng = rng
        self.next = 0  # round robin (stage 0): the server for the next request

    def pick(self, loads: list[float]) -> int:
        return two_choices(loads, self.rng)


def least_outstanding(loads: list[float]) -> int:
    """The server with the fewest requests in flight (stage 1: herds when the loads are stale)."""
    return min(range(len(loads)), key=loads.__getitem__)


def two_choices(loads: list[float], rng: random.Random) -> int:
    """The less loaded of two servers picked at random."""
    a, b = rng.sample(range(len(loads)), 2)
    return a if loads[a] <= loads[b] else b
