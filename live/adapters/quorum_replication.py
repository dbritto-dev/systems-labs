"""The pictures for lab quorum_replication: the nodes, the clients' view, and the fan-out (the coordinator in
the middle, the five replicas on the right)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, PINK, RED, WHITE, YELLOW
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_fanout import FanoutAdapter, FanoutFrame, Leaf
from live.views.lanes_relay import Relay

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
            nodes[sick[0]] = {"slow": YELLOW, "isolate": PINK}.get(sick[1], RED)  # as in the fan-out picture
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


# ---------------------------------------------------------------- the fan-out picture: the coordinator and the replicas

N = 3  # replicas per key (as scenario.replicas_for)
SEND_WINDOW = 0.35  # a coordinator's first messages for an operation leave within this long of its start
OPS_MAX = 20.0  # operations waiting for a quorum at once that fill the coordinator's gauge
BEHIND_MAX = 30  # keys a replica is missing that fill its gauge
MAX_HOPS = 80


def _holders(key: int, nodes: int) -> set[int]:
    return {(key % nodes + j) % nodes for j in range(N)}


@adapts("quorum_replication", "fanout")
class QuorumFanout(FanoutAdapter):
    """The clients and the door as in the lanes picture; in the middle the coordinator (whichever node took
    the request: all five coordinate), its gauge the operations waiting for a quorum, its outline red while
    reads come back stale, orange while operations go unanswered. On the right the five replicas n0..n4,
    outlined by what they are missing (blue in sync, oranges behind, red down or cut off, orange slow); a
    replica's gauge is the keys it is behind on. Messages between nodes fly between the two: an operation's
    requests to the replicas that hold its key (a write white, a read blue), their answers back in green, a
    late write to a replica (read repair, a hint handed off, a retry) in orange; an operation that ended in a
    stale read is red all the way, and a message the network dropped stops half way, red. A node that asks no other node (one copy) gets
    the request itself: it flies to it and ends there."""

    def frame(self, variant: str, t: float, users: int) -> FanoutFrame:
        from labs.quorum_replication import lab
        from labs.quorum_replication.scenario import PUT
        from live.worlds.quorum_replication import (
            MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_END, OP_KEY, OP_KIND, OP_NODE, OP_OK, OP_STALE, OP_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FanoutFrame()
        lane = QuorumLanes(w).frame(variant, t, users)
        by_node: dict[int, list[tuple]] = {}  # coordinator -> its operations near t
        for o in run.rows("ops", t - DROP_FADE * 8 - 2.0, t + 1e-9):
            by_node.setdefault(o[OP_NODE], []).append(o)

        def op_for(coord: int, replica: int, at: float):
            """The operation `coord` just took that this message to `replica` asks about, if any."""
            for o in by_node.get(coord, ()):
                if o[OP_START] <= at <= o[OP_START] + SEND_WINDOW and replica in _holders(o[OP_KEY], lab.NODES):
                    return o
            return None

        red, hops = [], []
        asked: dict[tuple[int, int], list[tuple]] = {}  # (coordinator, replica) -> operations still waiting
        for m in run.rows("msgs", t - DROP_FADE * 8 - 1.0, t + 1e-9):  # a slow node's take ~8x longer
            src, dest, sent, arrived = m[MSG_SRC], m[MSG_DEST], m[MSG_SENT], m[MSG_ARRIVED]
            waiting = asked.get((dest, src))
            if waiting:  # a replica answers what it was asked
                ans, req = waiting.pop(0), None
            else:
                ans, req = None, op_for(src, dest, sent)
                if req is not None:
                    asked.setdefault((src, dest), []).append(req)
            if (arrived is None and t - sent >= DROP_FADE) or (arrived is not None and t >= arrived):
                continue
            if req is not None:  # the coordinator asks a replica
                leaf, back, colour = dest, False, RED if req[OP_STALE] else WHITE if req[OP_KIND] == PUT else BLUE
            elif ans is not None:
                leaf, back, colour = src, True, RED if ans[OP_STALE] else GREEN
            else:  # anything else a node sends: repair (read repair, a hint handed off, a retry)
                leaf, back, colour = dest, False, EXTRA2
            if arrived is None:  # dropped: it stops half way
                red.append((leaf, min(0.5, (t - sent) / DROP_FADE), RED, back))
            else:
                p = (t - sent) / max(1e-6, arrived - sent)
                (red if colour == RED else hops).append((leaf, p, colour, back))
        talking = {m[MSG_SRC] for m in run.rows("msgs", t - 2.0, t + 1e-9)}
        for o in run.active("ops", t, OP_END):  # a node that asks no one: the request stops at it
            if o[OP_NODE] not in talking:
                p = (t - o[OP_START]) / max(1e-6, o[OP_END] - o[OP_START])
                (red if o[OP_STALE] else hops).append(
                    (o[OP_NODE], p, RED if o[OP_STALE] else WHITE if o[OP_KIND] == PUT else BLUE, False))
        red = every(red, 30)
        hops = red + every(hops, MAX_HOPS - len(red))

        behind = w.behind_at(run, t)
        sick = w.sick_at(variant, t)
        leaves = []
        for i in range(lab.NODES):
            outline, text = _behind(behind[i]), f"n{i}"
            if sick is not None and sick[0] == i:  # the colour says it (the legend): slow, cut off, down
                outline = {"slow": YELLOW, "isolate": PINK}.get(sick[1], RED)
            leaves.append(Leaf(label=(text, WHITE if outline == BLUE else outline),
                               fill=min(1.0, behind[i] / BEHIND_MAX), gauge=_behind(max(1, behind[i])),
                               outline=OUTLINE if outline == BLUE else outline))
        recent = [o for o in run.rows("ops", t - RECENT, t + 1e-9) if o[OP_END] <= t]
        stale = any(o[OP_STALE] for o in recent)
        unanswered = any(not o[OP_OK] for o in recent)
        waiting = len(run.active("ops", t, OP_END))
        look = RED if stale else EXTRA2 if unanswered else OUTLINE
        relay = Relay(label=(w.s("fan_coordinator"), look), fill=waiting / OPS_MAX,
                      gauge=EXTRA2 if unanswered else BLUE, outline=look)
        return FanoutFrame(users=lane.users, flights=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                           door_color=lane.door_color, state=lane.state, relay=relay, leaves=leaves, hops=hops)
