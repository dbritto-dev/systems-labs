"""The pictures for lab kafka_style_log: two nodes and lin-kv."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_fanin import FaninAdapter, FaninFrame, Leaf

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


# ---------------------------------------------------------------- the fan-in picture: network, nodes, lin-kv

KV_MAX = 150  # messages per second to or from lin-kv that fill its gauge
NODE_MAX = 40  # client operations per second on one node that fill its gauge
MAX_HOPS, MAX_JOINS, MAX_CROSS = 30, 40, 30


@adapts("kafka_style_log", "fanin")
class KafkaLogFanin(FaninAdapter):
    """Sends, polls and commits come through the network (the door) to the nodes n0 and n1 (each gauge its
    client operations/s); a node flashes red, with the anomaly by its name, when it hands out a duplicate
    offset or loses a write or a commit. The nodes keep the log in lin-kv (the store, purple, orange while
    it is slow, its gauge its messages/s): those messages fly light orange; a node that passes a request
    to the key's owner sends it blue, on the line between the nodes."""

    def frame(self, variant: str, t: float, users: int) -> FaninFrame:
        from live.worlds.kafka_style_log import (
            AN_KIND, AN_NODE, ANOMALY_KEYS, KV, MSG_DEST, MSG_SENT, MSG_SRC, OP_BAD, OP_NODE, OP_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FaninFrame()
        lane = KafkaLogLanes(w).frame(variant, t, users)  # users, flights and outcomes, as in lanes
        ops = run.rows("ops", t - TRAVEL, t + 1e-9)
        bad = [o for o in ops if o[OP_BAD]]
        hops = [(o[OP_NODE], (t - o[OP_START]) / TRAVEL, RED if o[OP_BAD] else WHITE, False)
                for o in bad[:MAX_HOPS] + every([o for o in ops if not o[OP_BAD]], MAX_HOPS - len(bad[:MAX_HOPS]))]
        joins, cross = [], []
        msgs = run.rows("msgs", t - TRAVEL, t + 1e-9)
        for m in every([m for m in msgs if KV in (m[MSG_SRC], m[MSG_DEST])], MAX_JOINS):
            back = m[MSG_SRC] == KV
            joins.append((m[MSG_DEST] if back else m[MSG_SRC], (t - m[MSG_SENT]) / TRAVEL, EXTRA1, back))
        for m in every([m for m in msgs if KV not in (m[MSG_SRC], m[MSG_DEST])], MAX_CROSS):
            cross.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / TRAVEL, BLUE))

        flashing: dict[int, int] = {}
        for x in run.rows("anomalies", t - FLASH, t + 1e-9):
            flashing[x[AN_NODE]] = x[AN_KIND]
        mine = [0] * KV
        for o in run.rows("ops", t - 1, t + 1e-9):
            if 0 <= o[OP_NODE] < KV:
                mine[o[OP_NODE]] += 1
        leaves = []
        for j in range(KV):
            node = f"n{j}"
            if j in flashing:
                label = (w.s(f"fan_{ANOMALY_KEYS[flashing[j]]}", node=node), RED)
            else:
                label = (node, WHITE)
            leaves.append(Leaf(label, short=node, fill=mine[j] / NODE_MAX, gauge=BLUE,
                               outline=RED if j in flashing else OUTLINE))

        inc = w.incident_at(variant, t)
        slow = inc is not None and inc.kind == "slowkv"
        recent = run.rows("anomalies", t - 2, t + 1e-9)
        if recent:
            state = (w.anomaly(recent[-1][AN_KIND]).upper(), RED)
        elif inc is not None and inc.kind == "burst":
            state = (w.s("state_hot", k=w.hot_key(run, inc).upper()), EXTRA2)
        elif slow:
            state = (w.s("state_kv_slow"), EXTRA2)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        kv = sum(1 for m in run.rows("msgs", t - 1, t + 1e-9) if KV in (m[MSG_SRC], m[MSG_DEST]))
        return FaninFrame(users=lane.users, flights=lane.flights, outcomes=lane.outcomes, fill=kv / KV_MAX,
                          gauge=EXTRA2 if kv > KV_MAX * 0.8 else BLUE, outline=EXTRA2 if slow else PURPLE,
                          state=state, leaves=leaves, hops=hops, joins=joins, cross=cross, peers=True,
                          door_label=(w.s("fan_network"), DIM))
