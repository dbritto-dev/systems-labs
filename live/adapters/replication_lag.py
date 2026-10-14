"""The cluster picture for lab replication_lag: the primary (top left) and replicas r1..r4."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import BLUE, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

DROP_FADE = 0.6  # seconds a wrong read stays on screen
READ_SHOWN = 0.12  # a read dot flies for ~100 ms (slowed down: a real read takes a few ms)
WRITE_SHOWN = 30.0  # replication still on its way can be this old (a restarted replica's backlog)
MAX_FLIGHTS = 90


@adapts("replication_lag", "cluster")
class ReplicationLagCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.replication_lag import (
            READ_MONO, READ_NODE, READ_OK, READ_RYW, READ_START, WRITE_LSN, WRITE_T,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for row in run.rows("writes", t - WRITE_SHOWN, t + 1e-9):  # the primary sends each write on
            for i, delay in enumerate(row[WRITE_LSN + 1:]):
                if t < row[WRITE_T] + delay:
                    flights.append((0, i + 1, (t - row[WRITE_T]) / delay, BLUE))
        for r in run.rows("reads", t - DROP_FADE, t + 1e-9):
            if not r[READ_OK] or r[READ_RYW] or r[READ_MONO]:
                drops.append((-1, r[READ_NODE], (t - r[READ_START]) / DROP_FADE))
            elif t - r[READ_START] < READ_SHOWN:
                flights.append((-1, r[READ_NODE], min(1.0, (t - r[READ_START]) / 0.1), WHITE))
        return ClusterFrame(nodes=w.node_colours(run, t), flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=w.state_at(variant, t))
