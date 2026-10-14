"""Lab canary_releases: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "canary_releases",
    "params": {"rate": Param(200.0)},
}

BASELINE_WINDOW = 15.0  # seconds before a deploy used as the baseline
SETTLE = 2.0  # seconds after a window closes before it is judged (every request ends within 1 s)

BASELINE_MAX = 0.01  # errors before the deploy (the live build is fine)
HURT_MAX = 0.005  # requests hurt by the new build (failed or slowed by it) / every request of the release window
FULL_MAX = 0  # bad builds that reach 100% of the traffic
ALARMS_MAX = 0  # good builds rolled back (false alarms)
ROLLOUT_MAX = 90.0  # seconds from the deploy to 100% for a good build


def stage_of(split: bool, baseline_ok: bool, hurt_ok: bool, full_ok: bool, alarms_ok: bool,
             rollout_ok: bool) -> int:
    """Judge the stage from what the first release (a latency regression) did: 0 everywhere at once, 1 a
    canary with fixed rules, 2 a staged canary compared with the baseline."""
    if not split:
        return 0  # the router never split the traffic: every user got the new build at once
    if not all((baseline_ok, hurt_ok, full_ok, alarms_ok, rollout_ok)):
        return 1  # a canary, but it let the slow build through (or rolled back a good one, or took too long)
    return 2
