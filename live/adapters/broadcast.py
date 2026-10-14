"""The pictures for lab broadcast."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


def _behind(missing: int) -> tuple[int, int, int]:
    if missing == 0:
        return BLUE
    return EXTRA1 if missing <= 3 else EXTRA2 if missing <= 10 else EXTRA3


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
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

SLOW = (0.25, 0.5, 0.8)  # seconds a client has waited before it turns light, mid, deep orange
GAUGE_MAX = 600  # messages per second between nodes that fill the cluster's gauge


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


@adapts("broadcast", "lanes")
class BroadcastLanes(LaneAdapter):
    """The clients' view: broadcasts and reads waiting on the cluster; the door is the network."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.broadcast import OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = _client_lanes(run, t, users, "ops", OP_START, OP_END, lambda o: not o[OP_OK])
        fill, gauge = _gauge(run, t)
        split = w.groups_at(variant, t) is not None
        words = w.screen.STATES
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=split, fill=fill, gauge=gauge,
                         outline=RED if split else OUTLINE,
                         state=(words["partitioned"], RED) if split else (words["connected"], GREEN))
