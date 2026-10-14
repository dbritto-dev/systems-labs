"""Lab canary_releases: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~200 requests/s to four endpoints (/home 55%, /search 25%, /cart 15%, /pay 5%). A router
spreads them over the instances running the live build: ~0.3% errors, p99 ~160 ms.

Every couple of minutes the team ships a new build: a RELEASE. For each one the scenario makes a
`Release()` and calls `release.decide(metrics)` at once and then every 5 s. You return the share of
the traffic the new build should get, from 0 to 1. The router sends that share of the requests (at
random, request by request) to instances running the new build: the CANARY. The rest go to the live
build: the BASELINE. Return 1.0 and the new build goes live everywhere (the release is done); return
0.0 and it is rolled back (the release is over). Right now `decide` returns 1.0 at once: every
user gets every new build.

Most builds are fine. Some are not, like in production: a CRASH LOOP (most requests fail at once:
a missing setting, a bad config), a subtle ERROR regression (0.3% errors become ~3%), a LATENCY
regression (a new N+1 query: +150-250 ms on a quarter of the requests, and no errors at all), or a
bug only on /PAY (a rounding change: 15-30% of payments fail, 5% of the traffic). And sometimes a
good build ships while a DEPENDENCY FLAKES (a database failover, a DNS blip): errors and slow
answers go up on both builds, and a naive rule blames the new one. A bad build that reaches 100%
stays live until someone on call rolls it back by hand, 2 minutes after the deploy.
The first release is always a latency regression at 0:20.

Do the stages in order, in this file:

  Stage 1  A canary with fixed rules: 5% of the traffic; roll back if its error rate is above
           ERROR_LIMIT; after BAKE seconds, everywhere.
  Stage 2  Compare the canary with the baseline over the same seconds, on errors AND slow answers,
           in total and per endpoint, with a statistical test and a minimum count; climb STEPS
           (5% -> 25% -> 50% -> 100%) once each step has baked; roll back on its own.

Check yourself:  uv run pytest labs/canary_releases
Peek at a solution (after trying!):  labs/canary_releases/reference.py
"""

from __future__ import annotations

import math  # noqa: F401  (stage 2: math.sqrt)
from dataclasses import dataclass

CANARY = 0.05  # stage 1: the share of the traffic the canary gets
BAKE = 60.0  # stage 1: seconds on the canary before going everywhere
ERROR_LIMIT = 0.05  # stage 1: roll back above this error rate (loose, or the noise rolls back good builds)
STEPS = (0.05, 0.25, 0.50, 1.0)  # stage 2: the shares of the traffic to climb, one at a time
STEP_BAKE = 20.0  # stage 2: seconds a step must last before the next one
MIN_SAMPLES = 200  # stage 2: canary requests a step needs before the next one
MIN_BAD = 5  # stage 2: never blame the canary for fewer bad answers than this
Z_LIMIT = 4.0  # stage 2: how many standard errors worse is "worse" (strict: you test 10 things every 5 s)


@dataclass(frozen=True, slots=True)
class Counts:
    """One build's answers since the router last changed its split.

      requests  answered requests
      errors    of those, errors (5xx)
      slow      of those, answered fine but slower than 250 ms
    """

    requests: int
    errors: int
    slow: int


@dataclass(frozen=True, slots=True)
class Metrics:
    """What `decide` sees, every 5 s of a release.

      t          now, in seconds
      since      when this release started (its build was deployed)
      weight     the share of the traffic the canary gets now (0.0 at the first call)
      step_age   seconds since the router last changed the split
      canary     the new build's Counts since then (the same seconds as the baseline's)
      baseline   the live build's Counts since then
      endpoints  per endpoint ("home", "search", "cart", "pay"): (canary Counts, baseline Counts)
    """

    t: float
    since: float
    weight: float
    step_age: float
    canary: Counts
    baseline: Counts
    endpoints: dict[str, tuple[Counts, Counts]]


class Release:
    """Ships one build. The scenario makes one Release per build.

    Contract:
      - `decide(m)` is called when the build is deployed and then every 5 s, until it returns 1.0 or
        0.0. It returns a float from 0 to 1: the share of the traffic the new build gets until the
        next call. 1.0 = it goes live everywhere (done); 0.0 = roll it back (done); anything in
        between = a canary of that size.
      - The router measures each split on its own: when your answer changes the share, the Counts
        start again from zero (so the canary and the baseline are always compared over the same
        seconds).
      - A release still running 2 minutes after its deploy is cancelled (rolled back).
    """

    def decide(self, m: Metrics) -> float:
        # Stage 1: return fixed_canary(m) instead.
        #
        # Stage 2: return ramp(m) instead.
        return 1.0


def fixed_canary(m: Metrics) -> float:
    """Stage 1. A canary with fixed rules: 0.0 (roll back) when the canary has answered requests and
    its error rate (m.canary.errors / m.canary.requests) is above ERROR_LIMIT; 1.0 (everywhere) once
    the release has run BAKE seconds (m.t - m.since); else CANARY.

    This is how many teams start, and it catches the crash loop in seconds, on 5% of the users. Then
    watch: the latency regression has no errors, so it bakes quietly and goes everywhere. And a
    fixed number cannot tell a bad build from a bad moment: when a dependency flakes, the canary's
    errors go up too (so do the live build's), and the rule rolls back a good build. Lower the limit
    and the noise rolls back good builds; raise it and a subtle regression slips under it.
    """
    raise NotImplementedError("TODO stage 1: fixed_canary(m)")


def z_score(bad_a: int, n_a: int, bad_b: int, n_b: int) -> float:
    """Stage 2. A two-proportion z-test: how many standard errors the bad share of a (bad_a out of
    n_a) is above the bad share of b. 0.0 when either n is 0, or when nothing at all is bad.

        pooled = (bad_a + bad_b) / (n_a + n_b)
        se     = sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
        z      = (bad_a / n_a - bad_b / n_b) / se

    Hint: z_score(30, 1000, 30, 1000) == 0.0; z_score(30, 1000, 3, 1000) is about 4.7.
    """
    raise NotImplementedError("TODO stage 2: z_score(bad_a, n_a, bad_b, n_b)")


def worse(canary: Counts, baseline: Counts) -> bool:
    """Stage 2. True when the canary is significantly worse than the baseline: on errors, or on slow
    answers, it has at least MIN_BAD of them AND its z_score against the baseline is above Z_LIMIT.

    Against the baseline, not against a fixed number: when a dependency flakes, both builds get
    worse together and the test sees no difference. MIN_BAD stops one unlucky error on a small
    canary from looking like 10x the baseline. Z_LIMIT is strict because you run this test 10 times
    every 5 s (errors and slow, in total and per endpoint): at 3 one of them crosses by chance now
    and then, and a good build is rolled back.

    Hint: for (c, b) in ((canary.errors, baseline.errors), (canary.slow, baseline.slow)): ...
    """
    raise NotImplementedError("TODO stage 2: worse(canary, baseline)")


def ramp(m: Metrics) -> float:
    """Stage 2. A staged canary that rolls back on its own:

      - 0.0 when the canary is worse(m.canary, m.baseline), or worse on any one endpoint
        (m.endpoints maps each one to its (canary, baseline) Counts): a bug only on /pay is 5% of
        the traffic, too diluted to show in the total until much of the traffic has it;
      - STEPS[0] at the first call (m.weight is 0.0);
      - the next share in STEPS after m.weight once the step has lasted STEP_BAKE seconds
        (m.step_age) on at least MIN_SAMPLES canary requests (enough samples before deciding);
      - else m.weight: hold, and keep measuring.

    Hint: min(s for s in STEPS if s > m.weight) is the next step.
    """
    raise NotImplementedError("TODO stage 2: ramp(m)")
