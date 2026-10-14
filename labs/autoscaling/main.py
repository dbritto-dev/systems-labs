"""Lab autoscaling: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~120-230 requests/s: the traffic follows a compressed day (busy at 1:00, quiet at
6:00), drifts, and comes in short bursts. A load balancer spreads it over a fleet of instances.
A warm instance does ~20 requests/s (2 at a time, ~100 ms each) and queues the rest; a user
whose request waits 2 s gives up (a 504).

Every 10 s the scenario calls your `Autoscaler.desired(metrics)`: you return how many
instances the fleet should have, and it launches or terminates instances to get there
(between MIN_INSTANCES and MAX_INSTANCES). A new instance BOOTS for 20-35 s (you pay for
it, it serves nothing), then serves while it WARMS UP (cold caches, a cold JIT: 2x slower at
first, warm after 20 s). Cost is instance-seconds: every instance you have, booting or not.
Right now the fleet is fixed: `desired` returns what you already have.

At random times, like in production: the traffic SURGES (a TV ad, a viral post), DROPS (a
region fails over away), the CPU gets NOISY (a batch job on the same hosts: CPU goes up, the
capacity does not) or a rolling deploy restarts the instances COLD. The first incident is
always a 2x surge at 0:20.

Do the stages in order, in this file:

  Stage 1  CPU thresholds: one instance more above 70% CPU, one less below 30%.
  Stage 2  Target tracking: the fleet the traffic needs at TARGET_RPS requests/s per
           instance, in one proportional step; scale in only after STABILISE seconds.

Check yourself:  uv run pytest labs/autoscaling
Peek at a solution (after trying!):  labs/autoscaling/reference.py
"""

from __future__ import annotations

import math  # noqa: F401  (stage 2: math.ceil)
from collections import deque
from dataclasses import dataclass

TARGET_RPS = 10.0  # requests/s per instance to aim for: half of what a warm one can do (the headroom)
SCALE_OUT_CPU = 0.70  # stage 1: add an instance above this CPU
SCALE_IN_CPU = 0.30  # stage 1: remove one below this CPU
STABILISE = 40.0  # stage 2: seconds a lower recommendation must last before you scale in
MIN_INSTANCES = 2  # the scenario never goes below this ...
MAX_INSTANCES = 40  # ... or above this, whatever you return


@dataclass(frozen=True, slots=True)
class Metrics:
    """What the autoscaler sees every 10 s (averages over the last 10 s).

      t          now, in seconds
      instances  every instance you pay for: booting, warming up and warm
      booting    launched, not serving yet (20-35 s)
      warming    serving, but still slow (cold caches, a cold JIT)
      rps        requests/s the users sent (from the load balancer)
      cpu        average CPU of the serving instances, 0 to 1 (anything else on the
                 host counts too: a batch job, a cold JIT)
      in_flight  average requests in flight per serving instance (queued or running)
    """

    t: float
    instances: int
    booting: int
    warming: int
    rps: float
    cpu: float
    in_flight: float

    @property
    def serving(self) -> int:
        """Instances taking requests (warming up or warm)."""
        return self.instances - self.booting


class Autoscaler:
    """Decides the size of the fleet.

    Contract:
      - `desired(m)` is called every 10 s with the Metrics of the last 10 s and returns an
        int: how many instances you want (instances you already have included). The
        scenario clamps it to MIN_INSTANCES..MAX_INSTANCES; when it is more than you have it
        launches the rest (they boot), when it is less it terminates the extra ones (those
        still booting first).
      - The scenario makes one Autoscaler per run; keep whatever you need in `self`.
    """

    def __init__(self) -> None:
        self.wants: deque[tuple[float, int]] = deque()  # stage 2: (t, recommendation), the last STABILISE s

    def desired(self, m: Metrics) -> int:
        # Stage 1: return cpu_step(m.cpu, m.instances) instead.
        #
        # Stage 2: return self.stabilised(m.t, target_tracking(m)) instead.
        return m.instances

    def stabilised(self, t: float, want: int) -> int:
        """Stage 2. Scale out at once, scale in slowly: remember each recommendation `want` with its
        time `t` in self.wants, forget those older than STABILISE seconds, and return the highest
        one left.

        So when the traffic jumps you grow at once (the new recommendation is the highest), but
        a dip only shrinks the fleet once every recommendation of the last STABILISE seconds
        agrees. Without it every burst adds instances and the next dip removes them again:
        flapping (and each new instance boots and warms up cold for nothing).

        Hint: append (t, want); popleft while self.wants[0][0] <= t - STABILISE; return the
        max of the wants.
        """
        raise NotImplementedError("TODO stage 2: Autoscaler.stabilised(t, want)")


def cpu_step(cpu: float, instances: int) -> int:
    """Stage 1. The fleet size after one threshold rule: instances + 1 when `cpu` is above
    SCALE_OUT_CPU, instances - 1 when it is below SCALE_IN_CPU, else instances.

    This is how many autoscalers start (a CPU alarm and a step of one). Then watch: during a
    surge the fleet grows by one instance every 10 s, and each one boots for 20-35 s, so it
    is always behind; requests time out. And CPU is not the traffic: when a batch job runs
    on the same hosts, CPU goes up and the rule adds instances nobody needs; while a deploy
    restarts instances cold, their CPU goes up too.
    """
    raise NotImplementedError("TODO stage 1: cpu_step(cpu, instances)")


def target_tracking(m: Metrics) -> int:
    """Stage 2. How many instances the traffic needs, in one proportional step: m.rps divided
    by TARGET_RPS, rounded up, and at least MIN_INSTANCES.

    It tracks the load (requests/s), not CPU, so a noisy neighbour or a cold JIT does not
    move it. TARGET_RPS is half of what a warm instance can do: that headroom absorbs the
    bursts, and the growth of a surge during the 30-60 s new instances take to boot and
    warm up.

    Warm-up accounting: the result is the whole fleet, booting and warming instances
    included (they are part of `m.instances` already, and will serve soon). Do NOT add
    instances for the ones not serving yet, as in `m.instances + needed - m.serving`: every
    10 s the ones still booting would be ordered again, and the fleet overshoots.

    Hint: max(MIN_INSTANCES, math.ceil(m.rps / TARGET_RPS)).
    """
    raise NotImplementedError("TODO stage 2: target_tracking(m)")
