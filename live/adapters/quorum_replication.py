"""The cluster picture for lab quorum_replication."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


def _behind(keys: int) -> tuple[int, int, int]:
    if keys == 0:
        return BLUE
    return EXTRA1 if keys <= 3 else EXTRA2 if keys <= 10 else EXTRA3


@adapts("quorum_replication", "cluster")
class QuorumCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.quorum_replication import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_NODE, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        nodes = [_behind(k) for k in w.behind_at(run, t)]
        sick = w.sick_at(variant, t)
        if sick is not None:
            nodes[sick[0]] = ORANGE if sick[1] == "slow" else RED
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE * 8, t + 1e-9):  # a slow node's messages take ~8x longer
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                if t - m[MSG_SENT] < DROP_FADE:
                    drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client requests on their way (~100 ms)
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        words = w.screen.STATES
        if sick is None:
            state = (words["healthy"], GREEN)
        elif sick[1] == "slow":
            state = (w.s("state_sick", state=words["degraded"], node=f"n{sick[0]}"), ORANGE)
        else:
            key = "partitioned" if sick[1] == "isolate" else "down"
            state = (w.s("state_sick", state=words[key], node=f"n{sick[0]}"), RED)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 30), state=state)
