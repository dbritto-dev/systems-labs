"""Lab canary_releases: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import math
from dataclasses import dataclass

CANARY = 0.05
BAKE = 60.0
ERROR_LIMIT = 0.05
STEPS = (0.05, 0.25, 0.50, 1.0)
STEP_BAKE = 20.0
MIN_SAMPLES = 200
MIN_BAD = 5
Z_LIMIT = 4.0


@dataclass(frozen=True, slots=True)
class Counts:
    requests: int
    errors: int
    slow: int


@dataclass(frozen=True, slots=True)
class Metrics:
    t: float
    since: float
    weight: float
    step_age: float
    canary: Counts
    baseline: Counts
    endpoints: dict[str, tuple[Counts, Counts]]


class Release:
    def decide(self, m: Metrics) -> float:
        return ramp(m)


def fixed_canary(m: Metrics) -> float:
    """5% of the traffic, roll back above a fixed error rate, everywhere after a fixed bake (stage 1)."""
    c = m.canary
    if c.requests and c.errors / c.requests > ERROR_LIMIT:
        return 0.0
    if m.t - m.since >= BAKE:
        return 1.0
    return CANARY


def z_score(bad_a: int, n_a: int, bad_b: int, n_b: int) -> float:
    """Two-proportion z-test: how many standard errors a's bad share is above b's."""
    if not n_a or not n_b:
        return 0.0
    pooled = (bad_a + bad_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    return 0.0 if se == 0 else (bad_a / n_a - bad_b / n_b) / se


def worse(canary: Counts, baseline: Counts) -> bool:
    """The canary is significantly worse on errors or on slow answers, with at least MIN_BAD of them."""
    for c_bad, b_bad in ((canary.errors, baseline.errors), (canary.slow, baseline.slow)):
        if c_bad >= MIN_BAD and z_score(c_bad, canary.requests, b_bad, baseline.requests) > Z_LIMIT:
            return True
    return False


def ramp(m: Metrics) -> float:
    """Compare with the baseline (in total and per endpoint); roll back when worse; else climb STEPS once a
    step has baked STEP_BAKE seconds on MIN_SAMPLES canary requests."""
    if worse(m.canary, m.baseline) or any(worse(c, b) for c, b in m.endpoints.values()):
        return 0.0
    if m.weight == 0.0:
        return STEPS[0]
    if m.step_age >= STEP_BAKE and m.canary.requests >= MIN_SAMPLES:
        return min(s for s in STEPS if s > m.weight)
    return m.weight
