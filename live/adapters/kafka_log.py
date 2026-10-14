"""The pictures for lab kafka_log: two nodes and lin-kv."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

TRAVEL = 0.3  # seconds a dot takes to cross (cosmetic: messages really take ~10 ms)
FLASH = 0.6  # seconds a node stays red after an anomaly it caused
MAX_FLIGHTS = 60


@adapts("kafka_log", "cluster")
class KafkaLogCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.kafka_log import (
            AN_NODE, KV, MSG_DEST, MSG_SENT, MSG_SRC, OP_BAD, OP_NODE, OP_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        inc = w.incident_at(variant, t)
        flashing = {x[AN_NODE] for x in run.rows("anomalies", t - FLASH, t + 1e-9)}
        nodes = [RED if i in flashing else BLUE for i in range(KV)]
        nodes.append(EXTRA2 if inc is not None and inc.kind == "slowkv" else PURPLE)
        flights = []
        for m in run.rows("msgs", t - TRAVEL, t + 1e-9):
            colour = EXTRA1 if KV in (m[MSG_SRC], m[MSG_DEST]) else BLUE
            flights.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / TRAVEL, colour))
        for o in run.rows("ops", t - TRAVEL, t + 1e-9):
            flights.append((-1, o[OP_NODE], (t - o[OP_START]) / TRAVEL, RED if o[OP_BAD] else WHITE))
        recent = run.rows("anomalies", t - 2, t + 1e-9)
        if recent:
            from live.worlds.kafka_log import AN_KIND
            state = (w.anomaly(recent[-1][AN_KIND]).upper(), RED)
        elif inc is not None and inc.kind == "burst":
            state = (w.s("state_hot", k=w.hot_key(run, inc).upper()), EXTRA2)
        elif inc is not None:
            state = (w.s("state_kv_slow"), EXTRA2)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), state=state)


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


@adapts("kafka_log", "lanes")
class KafkaLogLanes(LaneAdapter):
    """The clients' view: sends, polls and commits; the door is lin-kv, orange while it is slow."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.kafka_log import OP_BAD, OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = _client_lanes(run, t, users, "ops", OP_START, OP_END,
                                                   lambda o: not o[OP_OK] or o[OP_BAD])
        fill, gauge = _gauge(run, t)
        inc = w.incident_at(variant, t)
        slow = inc is not None and inc.kind == "slowkv"
        anomaly = bool(run.rows("anomalies", t - 2, t + 1e-9))
        words = w.screen.STATES
        if anomaly:
            state = (w.s("lanes_anomaly"), RED)
        elif slow:
            state = (w.s("lanes_kv_slow"), EXTRA2)
        elif inc is not None:
            state = (words["busy"], EXTRA2)
        else:
            state = (words["healthy"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=EXTRA2 if slow else None,
                         fill=fill, gauge=gauge, outline=RED if anomaly else OUTLINE, state=state)
