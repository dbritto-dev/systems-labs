"""The cluster picture for lab unique_ids."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import BLUE, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

HOP = 0.1  # a client request or reply takes about this long on the wire
DROP_FADE = 0.6
DUP_FLASH = 1.0  # a node that handed out a duplicate stays red this long


@adapts("unique_ids", "cluster")
class UniqueIdsCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.unique_ids import lab
        from live.worlds.unique_ids import (
            MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_DUP, OP_END, OP_NODE, OP_OK, OP_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        nodes = [BLUE] * lab.NODES
        skew = w.skewed_at(variant, t)
        if skew is not None:
            nodes[skew[0]] = EXTRA2
        flights, drops = [], []
        span = run.max_dur.get("ops", 0.0)
        for o in run.rows("ops", t - span - 0.01, t + 1e-9):
            if o[OP_DUP] and o[OP_END] <= t < o[OP_END] + DUP_FLASH:
                nodes[o[OP_NODE]] = RED
            if t < o[OP_START] + HOP:  # the request on its way
                flights.append((-1, o[OP_NODE], (t - o[OP_START]) / HOP, WHITE))
            elif o[OP_END] - HOP <= t < o[OP_END]:  # the reply on its way back
                colour = RED if o[OP_DUP] or not o[OP_OK] else GREEN
                flights.append((o[OP_NODE], -1, 1 - (o[OP_END] - t) / HOP, colour))
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            if m[MSG_ARRIVED] is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < m[MSG_ARRIVED]:
                p = (t - m[MSG_SENT]) / max(1e-6, m[MSG_ARRIVED] - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        groups = w.groups_at(variant, t)
        states = w.screen.STATES
        parts = []
        if groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            parts.append(f"{states['partitioned']} {' | '.join(map(str, sizes))}")
        if skew is not None:
            parts.append(w.s("state_clock", node=skew[0], seconds=skew[1]))
        state = (("  ".join(parts), RED if groups is not None else EXTRA2) if parts
                 else (states["connected"], GREEN))
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, 80), drops=every(drops, 30),
                            state=state)
