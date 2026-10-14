"""The pictures for lab txn."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

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


# ---------------------------------------------------------------- the lanes picture: the clients' view

SLOW = (0.25, 0.5, 0.8)  # seconds a client has waited before it turns light, mid, deep orange
GAUGE_MAX = 300  # messages per second between nodes that fill the cluster's gauge


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


@adapts("txn", "lanes")
class TxnLanes(LaneAdapter):
    """The clients' view: transactions waiting on the cluster; the door is the network."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.txn.scenario import TXN_BAD, TXN_END, TXN_OK, TXN_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = _client_lanes(run, t, users, "txns", TXN_START, TXN_END,
                                                   lambda o: not o[TXN_OK] or o[TXN_BAD])
        fill, gauge = _gauge(run, t)
        split = w.cut_at(variant, t) is not None
        g1b = bool(run.rows("anomalies", t - 1, t + 1e-9))
        words = w.screen.STATES
        if g1b:
            state = (w.s("lanes_g1b"), RED)
        elif split:
            state = (words["partitioned"], RED)
        else:
            state = (words["connected"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=split, fill=fill, gauge=gauge,
                         outline=RED if split or g1b else OUTLINE, state=state)
