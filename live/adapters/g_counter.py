"""The pictures for lab g_counter: 3 nodes, and seq-kv drawn as a fourth (purple) node."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

CONFLICT_FADE = 0.6  # seconds a failed compare-and-swap stays on screen
MAX_FLIGHTS = 80


@adapts("g_counter", "cluster")
class GCounterCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.g_counter.scenario import CLIENT_REQ, KV_ERR, KV_INDEX, KV_OK, KV_REQ
        from live.worlds.g_counter import MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC

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

SLOW = (0.25, 0.5, 0.8)  # seconds a client has waited before it turns light, mid, deep orange
GAUGE_MAX = 400  # messages per second between nodes that fill the cluster's gauge


def _id(start: float) -> int:
    return int(start * 1_000_003)  # client operations have no id: their start time is unique enough


def _client_lanes(run, t: float, users: int, table: str, start: int, end: int, bad) -> tuple:
    """Clients waiting (coloured by how long), requests flying to the door, answers fading at it."""
    waiting = {}
    for o in run.active(table, t, end):
        waited = t - o[start]
        colour = WHITE if waited < SLOW[0] else EXTRA1 if waited < SLOW[1] else EXTRA2 if waited < SLOW[2] else EXTRA3
        waiting[slot(_id(o[start]), users)] = (colour, True)
    flying = run.rows(table, t - FLY, t + 1e-9)
    flights = [(slot(_id(o[start]), users), (t - o[start]) / FLY, WHITE, False) for o in every(flying, FLIGHTS)]
    span = run.max_dur.get(table, 0.0)
    ended = [o for o in run.rows(table, t - BACK - span, t + 1e-9) if t - BACK <= o[end] <= t]
    outcomes = [(RED if bad(o) else GREEN, (t - o[end]) / BACK) for o in every(ended, OUTCOMES)]
    return waiting, flights, outcomes


def _gauge(run, t: float) -> tuple[float, tuple[int, int, int]]:
    fill = run.count("msgs", t - 1, t) / GAUGE_MAX
    return fill, EXTRA2 if fill > 0.8 else BLUE


@adapts("g_counter", "lanes")
class GCounterLanes(LaneAdapter):
    """The clients' view: adds and reads waiting on the nodes; the door is seq-kv, orange while it is slow."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.g_counter import OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = _client_lanes(run, t, users, "ops", OP_START, OP_END, lambda o: not o[OP_OK])
        fill, gauge = _gauge(run, t)
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
