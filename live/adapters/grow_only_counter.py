"""The pictures for lab grow_only_counter: 3 nodes, and seq-kv drawn as a fourth (purple) node."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, DIM, EXTRA2, GREEN, MUTED, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_fanin import FaninAdapter, FaninFrame, Leaf

CONFLICT_FADE = 0.6  # seconds a failed compare-and-swap stays on screen
MAX_FLIGHTS = 80


@adapts("grow_only_counter", "cluster")
class GCounterCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.grow_only_counter.scenario import CLIENT_REQ, KV_ERR, KV_INDEX, KV_OK, KV_REQ
        from live.worlds.grow_only_counter import MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        off = w.node_off(run, t)
        nodes = [(RED if n > 2 else EXTRA2) if n else BLUE for n in off] + [PURPLE]
        colours = {CLIENT_REQ: WHITE, KV_REQ: BLUE, KV_OK: GREEN, KV_ERR: RED}
        flights, drops = [], []
        for m in run.rows("msgs", t - CONFLICT_FADE, t + 1e-9):
            arrived, kind = m[MSG_ARRIVED], m[MSG_KIND]
            if kind == KV_ERR and arrived is not None and arrived <= t:
                drops.append((KV_INDEX, m[MSG_DEST], (t - arrived) / CONFLICT_FADE))  # a conflict, fading
            elif arrived is not None and m[MSG_SENT] <= t < arrived and kind in colours:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, colours[kind]))
        inc = w.incident_at(variant, t)
        conflicts = [c for c in run.rows("cas", t - 1, t + 1e-9)]
        share = sum(1 for c in conflicts if not c[2]) / len(conflicts) if conflicts else 0.0
        groups = w.groups_at(variant, t)
        if share >= 0.5:
            state = (w.s("state_conflicts", share=share), RED)
        elif groups is not None:
            state = (w.s("state_split", node=w.cut_off_at(variant, t)), RED)
        elif inc is not None:
            state = (w.s("state_burst" if inc.kind == "burst" else "state_slow", factor=inc.severity), EXTRA2)
        elif any(off):
            state = (w.s("state_off"), RED)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        if groups is not None:
            groups = groups + [-1]  # seq-kv: a service, every node still reaches it (as in Maelstrom)
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 30),
                            state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 400  # messages per second between nodes that fill the cluster's gauge





@adapts("grow_only_counter", "lanes")
class GCounterLanes(LaneAdapter):
    """The clients' view: adds and reads waiting on the nodes; the door is seq-kv, orange while it is slow."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.grow_only_counter import OP_END, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, lambda o: not o[OP_OK])
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        inc = w.incident_at(variant, t)
        slow = inc is not None and inc.kind == "slow"
        split = inc is not None and inc.kind == "split"
        cas = run.rows("cas", t - 1, t + 1e-9)
        conflicts = sum(1 for c in cas if not c[2]) / len(cas) if cas else 0.0
        words = w.screen.STATES
        if conflicts >= 0.5:
            state = (w.s("lanes_conflicts"), RED)
        elif split:
            state = (w.s("lanes_split"), RED)
        elif slow:
            state = (w.s("lanes_kv_slow"), EXTRA2)
        elif inc is not None:
            state = (words["busy"], EXTRA2)
        else:
            state = (words["healthy"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=EXTRA2 if slow else None,
                         fill=fill, gauge=gauge, outline=RED if conflicts >= 0.5 else OUTLINE, state=state)


# ---------------------------------------------------------------- the fan-in picture: network, nodes, seq-kv

TRAVEL = 0.25  # seconds a message dot takes along its line (cosmetic: messages really take ~20 ms)
KV_MAX = 150  # requests per second to seq-kv that fill its gauge
NODE_MAX = 40  # client requests per second to one node that fill its gauge
MAX_HOPS, MAX_JOINS = 30, 50


@adapts("grow_only_counter", "fanin")
class GCounterFanin(FaninAdapter):
    """Adds and reads come through the network (the door, orange while it is slow) to the nodes n0..n2
    (each gauge its client requests/s); a node turns orange, then red, while its reads are off. Each node
    keeps the count in seq-kv (the store, purple, its gauge the requests/s it gets): requests fly to it
    blue, answers fly back green, a compare-and-swap that conflicts flies back red."""

    def frame(self, variant: str, t: float, users: int) -> FaninFrame:
        from labs.grow_only_counter.scenario import CLIENT_REQ, KV_ERR, KV_INDEX, KV_OK, KV_REQ, NODES, REPLY
        from live.worlds.grow_only_counter import MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FaninFrame()
        lane = GCounterLanes(w).frame(variant, t, users)  # users, flights, outcomes and the door, as in lanes
        hops, joins = [], []
        msgs = run.rows("msgs", t - TRAVEL, t + 1e-9)
        for m in every([m for m in msgs if m[MSG_KIND] in (CLIENT_REQ, REPLY)], MAX_HOPS):
            back = m[MSG_KIND] == REPLY
            node = m[MSG_SRC] if back else m[MSG_DEST]
            hops.append((node, (t - m[MSG_SENT]) / TRAVEL, MUTED if back else WHITE, back))
        colours = {KV_REQ: BLUE, KV_OK: GREEN, KV_ERR: RED}
        to_kv = [m for m in msgs if m[MSG_KIND] in colours]
        to_kv = [m for m in to_kv if m[MSG_KIND] == KV_ERR] + [m for m in to_kv if m[MSG_KIND] != KV_ERR]  # red first
        for m in to_kv[:MAX_JOINS]:
            back = m[MSG_KIND] != KV_REQ
            node = m[MSG_DEST] if back else m[MSG_SRC]
            joins.append((node, (t - m[MSG_SENT]) / TRAVEL, colours[m[MSG_KIND]], back))

        off = w.node_off(run, t)
        mine = [0] * NODES
        for m in run.rows("msgs", t - 1, t + 1e-9):
            if m[MSG_KIND] == CLIENT_REQ and 0 <= m[MSG_DEST] < NODES:
                mine[m[MSG_DEST]] += 1
        leaves = []
        for j in range(NODES):
            node = f"n{j}"
            colour = (RED if off[j] > 2 else EXTRA2) if off[j] else None
            leaves.append(Leaf((node, colour or WHITE), short=node,  # reads off: orange, then red (the legend)
                               fill=mine[j] / NODE_MAX, gauge=BLUE, outline=colour or OUTLINE))

        kv = sum(1 for m in run.rows("msgs", t - 1, t + 1e-9) if m[MSG_KIND] == KV_REQ and m[MSG_DEST] == KV_INDEX)
        cas = run.rows("cas", t - 1, t + 1e-9)
        share = sum(1 for c in cas if not c[2]) / len(cas) if cas else 0.0
        inc = w.incident_at(variant, t)
        if share >= 0.5:
            state = (w.s("fan_conflicts", share=share), RED)
        elif inc is not None and inc.kind == "split":
            state = (w.s("state_split", node=w.cut_off_at(variant, t)), RED)
        elif inc is not None:
            state = (w.s("state_burst" if inc.kind == "burst" else "state_slow", factor=inc.severity), EXTRA2)
        elif any(off):
            state = (w.s("state_off"), RED)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        return FaninFrame(users=lane.users, flights=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, fill=kv / KV_MAX, gauge=EXTRA2 if kv > KV_MAX * 0.8 else BLUE,
                          outline=RED if share >= 0.5 else PURPLE, state=state, leaves=leaves, hops=hops,
                          joins=joins, door_label=(w.s("fan_network"), EXTRA2 if lane.door_color else DIM))
