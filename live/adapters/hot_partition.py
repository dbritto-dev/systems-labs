"""The pictures for lab hot_partition: cluster (the six partitions, coloured by how busy they are,
with requests flying to them) and lanes (the users' operations, your Counters as the door, the
store as the server)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every
from live.canvas import BLUE, EXTRA2, GREEN, PURPLE, RED
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

FLY = 0.3  # seconds a request takes to reach its partition (cosmetic: it takes ~1 ms)
DROP_FADE = 0.5  # seconds a throttled request stays on screen
MAX_FLIGHTS, MAX_DROPS = 70, 24


def _state(w, variant: str, t: float, utils: list[float]):
    """The words under the picture, and their colour."""
    from labs.hot_partition import lab

    hottest = max(range(len(utils)), key=lambda p: utils[p])
    run = w.runs[variant]
    inc = w.incident_at(variant, t)
    named = w.key_of(run, inc.index) if inc else None
    if utils[hottest] >= lab.BUSY_MAX:
        return w.s("state_melting", p=hottest, util=utils[hottest]), RED
    if named is not None and w.spread(variant, t) > 1:
        return w.s("state_spread", n=w.spread(variant, t), util=utils[hottest]), PURPLE
    return w.s("state_ok", util=utils[hottest]), GREEN


@adapts("hot_partition", "cluster")
class HotPartitionCluster(ClusterAdapter):
    """The six partitions (p0 ... p5, in two rows), each coloured by its utilisation over the last
    second: blue under 50%, oranges up to 90%, red above. Every request to the store flies from the
    users (left) to its partition: white a usual one, purple one on the hot key, orange an extra
    request a read made to fan in over sub-keys, blue folding sub-keys back. A request the
    partition throttled dies half way, in red."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.hot_partition import KIND_COLOURS, REQ_KIND, REQ_OK, REQ_P, REQ_T, util_colour

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        rows = run.rows("reqs", t - DROP_FADE, t + 1e-9)
        for r in every([r for r in rows if r[REQ_OK] and t - r[REQ_T] <= FLY], MAX_FLIGHTS):
            flights.append((-1, r[REQ_P], (t - r[REQ_T]) / FLY, KIND_COLOURS[r[REQ_KIND]]))
        for r in every([r for r in rows if not r[REQ_OK]], MAX_DROPS):
            drops.append((-1, r[REQ_P], (t - r[REQ_T]) / DROP_FADE))
        utils = w.utils(variant, t)
        word, colour = _state(w, variant, t, utils)
        return ClusterFrame(nodes=[util_colour(u) for u in utils], flights=flights, drops=drops,
                            state=(word, colour))


@adapts("hot_partition", "lanes")
class HotPartitionLanes(LaneAdapter):
    """Each user operation is a circle on the left, filled while it waits (white, then oranges the
    longer it waits). Operations fly to the door (your Counters); what came back fades there: green
    one request, orange a read that fanned in over sub-keys, blue a read served from the cache, red
    throttled. The server is the store: its gauge is the busiest partition's utilisation."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.hot_partition import lab
        from labs.hot_partition.scenario import THROTTLED
        from live.worlds.hot_partition import OP_END, OP_OK, OP_REQS, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            if o[OP_OK] == THROTTLED:
                return RED
            return BLUE if o[OP_REQS] == 0 else EXTRA2 if o[OP_REQS] > 1 else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                  rare_first=True)
        utils = w.utils(variant, t)
        busiest = max(utils)
        word, state_colour = _state(w, variant, t, utils)
        hottest = max(range(len(utils)), key=lambda p: utils[p])
        if busiest >= lab.BUSY_MAX:
            word = w.s("lanes_melting", p=hottest, util=busiest)
        elif state_colour != PURPLE:
            word = w.s("lanes_ok", util=busiest)
        else:
            word = w.s("lanes_spread", n=w.spread(variant, t))
        gauge = RED if busiest >= lab.BUSY_MAX else EXTRA2 if busiest >= 0.7 else BLUE
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, fill=busiest, gauge=gauge,
                         door_color=PURPLE if state_colour == PURPLE else None,
                         outline=RED if busiest >= lab.BUSY_MAX else OUTLINE, state=(word, state_colour))

