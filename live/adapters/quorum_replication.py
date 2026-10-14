"""The pictures for lab quorum_replication: the nodes, and the clients' view."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


def _behind(keys: int) -> tuple[int, int, int]:
    if keys == 0:
        return BLUE
    return EXTRA1 if keys <= 3 else EXTRA2 if keys <= 10 else EXTRA3


@adapts("quorum_replication", "cluster")
class QuorumCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.quorum_replication import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_NODE, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        nodes = [_behind(k) for k in w.behind_at(run, t)]
        sick = w.sick_at(variant, t)
        if sick is not None:
            nodes[sick[0]] = ORANGE if sick[1] == "slow" else RED
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE * 8, t + 1e-9):  # a slow node's messages take ~8x longer
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                if t - m[MSG_SENT] < DROP_FADE:
                    drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client requests on their way (~100 ms)
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        words = w.screen.STATES
        if sick is None:
            state = (words["healthy"], GREEN)
        elif sick[1] == "slow":
            state = (w.s("state_sick", state=words["degraded"], node=f"n{sick[0]}"), ORANGE)
        else:
            key = "partitioned" if sick[1] == "isolate" else "down"
            state = (w.s("state_sick", state=words[key], node=f"n{sick[0]}"), RED)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 300  # messages per second between nodes that fill the gauge
RECENT = 2.0  # seconds a stale or unanswered read keeps the state on it (~20 operations/s)


@adapts("quorum_replication", "lanes")
class QuorumLanes(LaneAdapter):
    """The clients' view: reads and writes through the coordinators (the door, orange or red while a
    node is sick) to the replicas (the server, its gauge the messages between nodes). An answer is green,
    red when a read missed the latest write (stale), orange when nobody answered in time."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.quorum_replication import OP_END, OP_OK, OP_STALE, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return RED if o[OP_STALE] else GREEN if o[OP_OK] else EXTRA2

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                   rare_first=True)
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        recent = [o for o in run.rows("ops", t - RECENT, t + 1e-9) if o[OP_END] <= t]
        stale = any(o[OP_STALE] for o in recent)
        unanswered = any(not o[OP_OK] for o in recent)
        sick = w.sick_at(variant, t)
        door = None if sick is None else ORANGE if sick[1] == "slow" else RED
        words = w.screen.STATES
        if stale:
            state = (w.s("lanes_stale"), RED)
        elif unanswered:
            state = (w.s("lanes_unanswered"), EXTRA2)
        elif sick is not None:
            key = "degraded" if sick[1] == "slow" else "partitioned" if sick[1] == "isolate" else "down"
            state = (words[key], ORANGE if sick[1] == "slow" else RED)
        else:
            state = (words["healthy"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=door, fill=fill,
                         gauge=gauge, outline=RED if stale else OUTLINE, state=state)
