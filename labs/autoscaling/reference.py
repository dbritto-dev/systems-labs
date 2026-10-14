"""Lab autoscaling: a working solution. Read it after you have tried main.py."""

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
        self.wants: deque[tuple[float, int]] = deque()  # (t, recommendation) of the last STABILISE s

    def desired(self, m: Metrics) -> int:
        return self.stabilised(m.t, target_tracking(m))

    def stabilised(self, t: float, want: int) -> int:
        """Scale out at once; scale in only to the highest recommendation of the last STABILISE s."""
        self.wants.append((t, want))
        while self.wants[0][0] <= t - STABILISE:
            self.wants.popleft()
        return max(w for _, w in self.wants)


def cpu_step(cpu: float, instances: int) -> int:
    """One instance more above SCALE_OUT_CPU, one less below SCALE_IN_CPU (stage 1: slow, and CPU lies)."""
    if cpu > SCALE_OUT_CPU:
        return instances + 1
    if cpu < SCALE_IN_CPU:
        return instances - 1
    return instances


def target_tracking(m: Metrics) -> int:
    """The fleet that puts TARGET_RPS on each instance: the traffic, not CPU, in one proportional step.
    Booting and warming instances are part of the fleet already (they are on their way): never order
    them again."""
    return max(MIN_INSTANCES, math.ceil(m.rps / TARGET_RPS))
