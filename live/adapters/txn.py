"""The cluster picture for lab txn."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import BLUE, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 60


@adapts("txn", "cluster")
class TxnCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.txn.scenario import TXN_NODE, TXN_START
        from live.worlds.txn import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        for r in run.rows("txns", t - 0.12, t + 1e-9):  # transactions on their way (~100 ms)
            flights.append((-1, r[TXN_NODE], min(1.0, (t - r[TXN_START]) / 0.1), WHITE))
        cut = w.cut_at(variant, t)
        n = len(w.stale_at(run, t))
        groups = None if cut is None else [1 if i == cut else 0 for i in range(n)]
        words = w.screen.STATES
        if cut is not None:
            state = (f"{words['partitioned']}  {w.s('state_cut', node=cut)}", RED)
        else:
            state = (words["connected"], GREEN)
        return ClusterFrame(nodes=w.node_colours(run, t), groups=groups, flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state)
