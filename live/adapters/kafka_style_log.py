"""The pictures for lab kafka_style_log: two nodes and lin-kv."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

TRAVEL = 0.3  # seconds a dot takes to cross (cosmetic: messages really take ~10 ms)
FLASH = 0.6  # seconds a node stays red after an anomaly it caused
MAX_FLIGHTS = 60


@adapts("kafka_style_log", "cluster")
class KafkaLogCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.kafka_style_log import (
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
            from live.worlds.kafka_style_log import AN_KIND
            state = (w.anomaly(recent[-1][AN_KIND]).upper(), RED)
        elif inc is not None and inc.kind == "burst":
            state = (w.s("state_hot", k=w.hot_key(run, inc).upper()), EXTRA2)
        elif inc is not None:
            state = (w.s("state_kv_slow"), EXTRA2)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 300  # messages per second between nodes that fill the cluster's gauge





@adapts("kafka_style_log", "lanes")
class KafkaLogLanes(LaneAdapter):
    """The clients' view: sends, polls and commits; the door is lin-kv, orange while it is slow."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.kafka_style_log import OP_BAD, OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END,
                                                   lambda o: not o[OP_OK] or o[OP_BAD])
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
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
