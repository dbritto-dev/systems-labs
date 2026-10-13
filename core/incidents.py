"""Production-like randomness: when things go wrong, and how traffic drifts.

Incidents arrive as a seeded random process, not on a timetable: the gaps
vary (sometimes two come close together, sometimes it is quiet for minutes),
durations have a long tail, and kinds and severities vary. Only the first
incident is fixed, so the first verdict of a run is always the same.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Planned:
    t0: float
    t1: float  # equal to t0 for an instant incident (a flush)
    kind: str
    severity: float = 1.0  # e.g. the share of calls that fail
    cause: str = ""  # what went wrong, in plain words


@dataclass(frozen=True, slots=True)
class Kind:
    name: str
    weight: float
    median: float = 0.0  # seconds; 0 = instant
    shortest: float = 0.0
    longest: float = 0.0
    severity: tuple[float, float] = (1.0, 1.0)
    causes: tuple[str, ...] = ()


def schedule(seed: int, first: Planned, kinds: list[Kind], mean_gap: float,
             quiet: float) -> Iterator[Planned]:
    """Incidents forever, in time order.

    After an incident ends there are at least `quiet` calm seconds (so each one
    can be judged on its own), then an exponential wait with mean `mean_gap`.
    Durations are log-normal around each kind's median.
    """
    rng = random.Random(seed * 7_919 + 104_729)
    yield first
    end = first.t1
    weights = [k.weight for k in kinds]
    while True:
        t0 = end + quiet + rng.expovariate(1.0 / mean_gap)
        kind = rng.choices(kinds, weights)[0]
        length = 0.0
        if kind.median > 0:
            length = rng.lognormvariate(math.log(kind.median), 0.6)
            length = min(kind.longest, max(kind.shortest, length))
        severity = rng.uniform(*kind.severity)
        cause = rng.choice(kind.causes) if kind.causes else ""
        yield Planned(round(t0, 1), round(t0 + length, 1), kind.name, round(severity, 2), cause)
        end = t0 + length


def rate_at(base: float, t: float, seed: int) -> float:
    """Traffic that drifts like a real day, compressed: ±~15% over a few minutes."""
    rng = random.Random(seed * 31 + 5)
    p1, p2 = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    return base * (1 + 0.10 * math.sin(2 * math.pi * t / 420 + p1)
                   + 0.05 * math.sin(2 * math.pi * t / 67 + p2))


def arrivals(base: float, seed: int, start: float, rng: random.Random) -> Iterator[float]:
    """Arrival times of a Poisson process whose rate drifts (by thinning)."""
    peak = base * 1.2
    t = start
    while True:
        t += rng.expovariate(peak)
        if rng.random() * peak <= rate_at(base, t, seed):
            yield t
