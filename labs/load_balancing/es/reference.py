"""Laboratorio load_balancing: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import random


class Balancer:
    def __init__(self, servers: int, rng: random.Random) -> None:
        self.servers = servers
        self.rng = rng
        self.next = 0  # por turnos (etapa 0): el servidor de la siguiente petición

    def pick(self, loads: list[float]) -> int:
        return two_choices(loads, self.rng)


def least_outstanding(loads: list[float]) -> int:
    """El servidor con menos peticiones en curso (etapa 1: va en manada si la carga es vieja)."""
    return min(range(len(loads)), key=loads.__getitem__)


def two_choices(loads: list[float], rng: random.Random) -> int:
    """El menos cargado de dos servidores elegidos al azar."""
    a, b = rng.sample(range(len(loads)), 2)
    return a if loads[a] <= loads[b] else b
