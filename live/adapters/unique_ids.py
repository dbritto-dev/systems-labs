"""The pictures for lab unique_ids."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

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


# ---------------------------------------------------------------- the lanes picture: the clients' view

SLOW = (0.25, 0.5, 0.8)  # seconds a client has waited before it turns light, mid, deep orange
GAUGE_MAX = 200  # messages per second between nodes that fill the cluster's gauge


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


@adapts("unique_ids", "lanes")
class UniqueIdsLanes(LaneAdapter):
    """The clients' view: echo and generate requests; the door is the network, red for duplicate ids."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.unique_ids import OP_DUP, OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = _client_lanes(run, t, users, "ops", OP_START, OP_END,
                                                   lambda o: not o[OP_OK] or o[OP_DUP])
        fill, gauge = _gauge(run, t)
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
