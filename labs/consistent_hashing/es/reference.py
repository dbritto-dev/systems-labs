"""Laboratorio consistent_hashing: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import bisect
import hashlib

VNODES = 200  # puntos en el anillo por nodo


def stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


class Router:
    def __init__(self, nodes: list[str]) -> None:
        self.ring: list[tuple[int, str]] = []
        for node in nodes:
            self.add(node)

    def add(self, node: str) -> None:
        for i in range(VNODES):
            bisect.insort(self.ring, (stable_hash(f"{node}#{i}"), node))

    def remove(self, node: str) -> None:
        self.ring = [point for point in self.ring if point[1] != node]

    def node_for(self, key: str) -> str:
        i = bisect.bisect_left(self.ring, (stable_hash(key), ""))
        return self.ring[i % len(self.ring)][1]  # pasado el último punto: vuelve al primero
