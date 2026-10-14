"""The pictures for lab unique_id_generation."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

HOP = 0.1  # a client request or reply takes about this long on the wire
DROP_FADE = 0.6
DUP_FLASH = 1.0  # a node that handed out a duplicate stays red this long


@adapts("unique_id_generation", "cluster")
class UniqueIdsCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.unique_id_generation import lab
        from live.worlds.unique_id_generation import (
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


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 200  # messages per second between nodes that fill the cluster's gauge





@adapts("unique_id_generation", "lanes")
class UniqueIdsLanes(LaneAdapter):
    """The clients' view: echo and generate requests; the door is the network, red for duplicate ids."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.unique_id_generation import OP_DUP, OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END,
                                                   lambda o: not o[OP_OK] or o[OP_DUP])
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        split = w.groups_at(variant, t) is not None
        skew = w.skewed_at(variant, t)
        span = run.max_dur.get("ops", 0.0)
        dups = any(o[OP_DUP] and t - 1 <= o[OP_END] <= t for o in run.rows("ops", t - 1 - span, t + 1e-9))
        words = w.screen.STATES
        if dups:
            state = (w.s("lanes_dups"), RED)
        elif split:
            state = (words["partitioned"], RED)
        elif skew is not None:
            state = (w.s("lanes_clock"), EXTRA2)
        else:
            state = (words["connected"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=split, fill=fill, gauge=gauge,
                         outline=RED if split or dups else EXTRA2 if skew is not None else OUTLINE, state=state)
