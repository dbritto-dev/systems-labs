"""The cluster picture for lab raft_consensus: nodes coloured by role, AppendEntries and votes in flight."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import BLUE, EXTRA1, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


@adapts("raft_consensus", "cluster")
class RaftCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.raft_consensus.scenario import DOWN, VOTE
        from live.worlds.raft_consensus import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, OP_NODE, OP_START, ROLE_COLOURS, name,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        roles = w.roles_at(variant, t)
        nodes = [ROLE_COLOURS.get(r, BLUE) for r in roles]
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, EXTRA1 if m[MSG_KIND] == VOTE else BLUE))
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client commands on their way
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        groups = w.groups_at(variant, t)
        words = w.screen.STATES
        down = [name(i) for i, r in enumerate(roles) if r == DOWN]
        inc = w.incident_at(variant, t)
        if groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            state = (f"{words['partitioned']}  {' | '.join(map(str, sizes))}", RED)
        elif down:
            state = (f"{words['down']}  {' '.join(down)}", RED)
        elif inc is not None and inc.kind == "slow":
            state = (f"{words['degraded']}  {inc.severity:.0f}x", RED)
        else:
            state = (words["connected"], GREEN)
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state)
