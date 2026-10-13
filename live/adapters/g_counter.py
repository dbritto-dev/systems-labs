"""The cluster picture for lab g_counter: 3 nodes, and seq-kv drawn as a fourth (purple) node."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import BLUE, EXTRA2, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

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
