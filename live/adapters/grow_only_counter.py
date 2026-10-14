"""The pictures for lab grow_only_counter: 3 nodes, and seq-kv drawn as a fourth (purple) node."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA2, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

CONFLICT_FADE = 0.6  # seconds a failed compare-and-swap stays on screen
MAX_FLIGHTS = 80


@adapts("grow_only_counter", "cluster")
class GCounterCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.grow_only_counter.scenario import CLIENT_REQ, KV_ERR, KV_INDEX, KV_OK, KV_REQ
        from live.worlds.grow_only_counter import MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        off = w.node_off(run, t)
        nodes = [(RED if n > 2 else EXTRA2) if n else BLUE for n in off] + [PURPLE]
        colours = {CLIENT_REQ: WHITE, KV_REQ: BLUE, KV_OK: GREEN, KV_ERR: RED}
        flights, drops = [], []
        for m in run.rows("msgs", t - CONFLICT_FADE, t + 1e-9):
            arrived, kind = m[MSG_ARRIVED], m[MSG_KIND]
            if kind == KV_ERR and arrived is not None and arrived <= t:
                drops.append((KV_INDEX, m[MSG_DEST], (t - arrived) / CONFLICT_FADE))  # a conflict, fading
            elif arrived is not None and m[MSG_SENT] <= t < arrived and kind in colours:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, colours[kind]))
        inc = w.incident_at(variant, t)
        conflicts = [c for c in run.rows("cas", t - 1, t + 1e-9)]
        share = sum(1 for c in conflicts if not c[2]) / len(conflicts) if conflicts else 0.0
        if share >= 0.5:
            state = (w.s("state_conflicts", share=share), RED)
        elif inc is not None:
            state = (w.s("state_burst" if inc.kind == "burst" else "state_slow", factor=inc.severity), EXTRA2)
        elif any(off):
            state = (w.s("state_off"), RED)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 400  # messages per second between nodes that fill the cluster's gauge





@adapts("grow_only_counter", "lanes")
class GCounterLanes(LaneAdapter):
    """The clients' view: adds and reads waiting on the nodes; the door is seq-kv, orange while it is slow."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.grow_only_counter import OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, lambda o: not o[OP_OK])
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        inc = w.incident_at(variant, t)
        slow = inc is not None and inc.kind != "burst"
        cas = run.rows("cas", t - 1, t + 1e-9)
        conflicts = sum(1 for c in cas if not c[2]) / len(cas) if cas else 0.0
        words = w.screen.STATES
        if conflicts >= 0.5:
            state = (w.s("lanes_conflicts"), RED)
        elif slow:
            state = (w.s("lanes_kv_slow"), EXTRA2)
        elif inc is not None:
            state = (words["busy"], EXTRA2)
        else:
            state = (words["healthy"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=EXTRA2 if slow else None,
                         fill=fill, gauge=gauge, outline=RED if conflicts >= 0.5 else OUTLINE, state=state)
