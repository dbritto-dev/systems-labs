"""The pictures for lab autoscaling: lanes (users → the load balancer as the door → the fleet as one server
whose gauge is the number of instances) and cluster (one node per instance slot: instances appear light
orange while they boot, purple while they warm up, blue once warm, red while their queue grows; empty
slots are dim)."""

from __future__ import annotations

from labs.autoscaling.scenario import BOOTING, EMPTY, MAX_INSTANCES, WARM_STATE, WARMING, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, client_lanes, every
from live.canvas import BLUE, GREEN, RED, RGB, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

EMPTY_SLOT: RGB = (40, 46, 56)  # a slot with no instance: room for the fleet to grow
OVERLOADED = 3 * WORKERS  # requests in flight on one instance that make it red (its queue is growing)


def _fleet(w, run, t: float):
    """(instances, booting, warming, needed, overloaded, sample) at t."""
    from live.worlds.autoscaling import S_BOOTING, S_CAPACITY, S_DEMAND, S_INSTANCES, S_WARMING, needed

    s = w.sample_at(run, t)
    if s is None:
        return 0, 0, 0, 0, False, None
    return (s[S_INSTANCES], s[S_BOOTING], s[S_WARMING], needed(s[S_DEMAND]), s[S_CAPACITY] < s[S_DEMAND], s)


def _timeouts(run, t: float) -> list[tuple]:
    """Requests that failed in the last BACK seconds."""
    from live.worlds.autoscaling import REQ_END, REQ_OK

    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", t - BACK - span, t + 1e-9) if t - BACK <= r[REQ_END] <= t and not r[REQ_OK]]


def _state(w, failing: bool, overloaded: bool, booting: int) -> tuple[str, RGB]:
    words = w.screen.STATES
    if failing:
        return words["overloaded"], RED
    if overloaded:
        return words["busy"], RED
    if booting:
        return words["busy"], BLUE
    return words["healthy"], GREEN


@adapts("autoscaling", "lanes")
class AutoscalingLanes(LaneAdapter):
    """Users wait for an answer (orange the longer they wait); requests fly to the door, the load balancer
    (shut in red while requests time out). The server is the fleet: its gauge is how many instances it has
    out of MAX_INSTANCES (light orange while some boot, purple while some warm up), its outline red while
    it has less capacity than the traffic. Under it: its state, the instances serving + those booting."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.autoscaling import BOOTING_C, REQ_END, REQ_OK, REQ_START, WARM_C, WARMING_C

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "requests", REQ_START, REQ_END,
                                                  colour=lambda r: GREEN if r[REQ_OK] else RED, rare_first=True)
        n, booting, warming, _, overloaded, _ = _fleet(w, run, t)
        failing = bool(_timeouts(run, t))
        state, colour = _state(w, failing, overloaded, booting)
        gauge = BOOTING_C if booting else WARMING_C if warming else WARM_C
        return LaneFrame(
            users=waiting, flights=flights, outcomes=outcomes, closed=failing,
            fill=n / MAX_INSTANCES, gauge=gauge, outline=RED if overloaded else OUTLINE,
            state=(w.s("fleet_state", state=state, n=n - booting, booting=booting), colour),
        )


@adapts("autoscaling", "cluster")
class AutoscalingCluster(ClusterAdapter):
    """One node per instance slot (MAX_INSTANCES of them): dim when empty, light orange while booting, purple
    while warming up, blue when warm, red while its queue grows. A sample of the requests flies from the
    users to the instance that got it; timeouts die in red on the way."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.autoscaling import (
            BOOTING_C,
            REQ_END,
            REQ_SLOT,
            REQ_START,
            S_LOADS,
            S_STATES,
            SHORT_C,
            WARM_C,
            WARMING_C,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        n, booting, _, need, overloaded, sample = _fleet(w, run, t)
        colours = {EMPTY: EMPTY_SLOT, BOOTING: BOOTING_C, WARMING: WARMING_C, WARM_STATE: WARM_C}
        if sample is None:
            nodes = [EMPTY_SLOT] * MAX_INSTANCES
        else:
            nodes = [SHORT_C if state != BOOTING and load >= OVERLOADED else colours[state]
                     for state, load in zip(sample[S_STATES], sample[S_LOADS])]
        flying = [r for r in run.rows("requests", t - FLY, t + 1e-9) if r[REQ_SLOT] >= 0]
        flights = [(-1, r[REQ_SLOT], (t - r[REQ_START]) / FLY, WHITE) for r in every(flying, 2 * FLIGHTS)]
        failed = _timeouts(run, t)
        drops = [(-1, max(0, r[REQ_SLOT]), (t - r[REQ_END]) / BACK) for r in every(failed, OUTCOMES)]
        state, colour = _state(w, bool(failed), overloaded, booting)
        text = w.s("cluster_state", state=state, n=n - booting, booting=booting, need=need)
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops, state=(text, colour))
