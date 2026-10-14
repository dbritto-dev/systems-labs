"""Laboratorio autoscaling: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

TARGET_RPS = 10.0
SCALE_OUT_CPU = 0.70
SCALE_IN_CPU = 0.30
STABILISE = 40.0
MIN_INSTANCES = 2
MAX_INSTANCES = 40


@dataclass(frozen=True, slots=True)
class Metrics:
    t: float
    instances: int
    booting: int
    warming: int
    rps: float
    cpu: float
    in_flight: float

    @property
    def serving(self) -> int:
        return self.instances - self.booting


class Autoscaler:
    def __init__(self) -> None:
        self.wants: deque[tuple[float, int]] = deque()  # (t, recomendación) de los últimos STABILISE s

    def desired(self, m: Metrics) -> int:
        return self.stabilised(m.t, target_tracking(m))

    def stabilised(self, t: float, want: int) -> int:
        """Crece enseguida; reduce solo hasta la recomendación más alta de los últimos STABILISE s."""
        self.wants.append((t, want))
        while self.wants[0][0] <= t - STABILISE:
            self.wants.popleft()
        return max(w for _, w in self.wants)


def cpu_step(cpu: float, instances: int) -> int:
    """Una instancia más sobre SCALE_OUT_CPU, una menos bajo SCALE_IN_CPU (etapa 1: lenta, y la CPU engaña)."""
    if cpu > SCALE_OUT_CPU:
        return instances + 1
    if cpu < SCALE_IN_CPU:
        return instances - 1
    return instances


def target_tracking(m: Metrics) -> int:
    """La flota que pone TARGET_RPS en cada instancia: el tráfico, no la CPU, en un paso proporcional.
    Las instancias que arrancan o se calientan ya son parte de la flota (están en camino): nunca las
    pidas otra vez."""
    return max(MIN_INSTANCES, math.ceil(m.rps / TARGET_RPS))
