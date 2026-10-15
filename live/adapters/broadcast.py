"""The pictures for lab broadcast."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


def _behind(missing: int) -> tuple[int, int, int]:
    if missing == 0:
        return BLUE
    return EXTRA1 if missing <= 3 else EXTRA2 if missing <= 10 else EXTRA3


def _grid_links(n: int) -> list[tuple[int, int]]:
    """The scenario's grid topology (core.net.Topology.grid): each node and its right and lower neighbour."""
    side = max(1, round(n ** 0.5))
    out = []
    for i in range(n):
        r, c = divmod(i, side)
        if c + 1 < side and i + 1 < n:
            out.append((i, i + 1))
        if i + side < n:
            out.append((i, i + side))
    return out


@adapts("broadcast", "cluster")
class BroadcastCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.broadcast import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_NODE, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        nodes = [_behind(m) for m in w.missing_at(run, t)]
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client requests on their way (~100 ms)
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        groups = w.groups_at(variant, t)
        words = w.screen.STATES
        if groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            state = (f"{words['partitioned']}  {' | '.join(map(str, sizes))}", RED)
        else:
            state = (words["connected"], GREEN)
        missing = w.missing_at(run, t)
        labels = [(f"−{m}", _behind(m)) if m else ("", WHITE) for m in missing]  # how many values each still lacks
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state, links=_grid_links(len(nodes)), labels=labels)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 600  # messages per second between nodes that fill the cluster's gauge





@adapts("broadcast", "lanes")
class BroadcastLanes(LaneAdapter):
    """The clients' view: broadcasts and reads waiting on the cluster; the door is the network."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.broadcast import OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, lambda o: not o[OP_OK])
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        split = w.groups_at(variant, t) is not None
        words = w.screen.STATES
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=split, fill=fill, gauge=gauge,
                         outline=RED if split else OUTLINE,
                         state=(words["partitioned"], RED) if split else (words["connected"], GREEN))
