"""The pictures for lab vector_clocks_crdts: the replicas gossiping (peers: on a pentagon; cluster: on a grid),
and the devices reading their carts (lanes)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, link_list, message_gauge, peer_traffic, sent_per_second
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import LINE, Leaf, PeersAdapter, PeersFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


def _diverged(carts: int) -> tuple[int, int, int]:
    if carts == 0:
        return BLUE
    return EXTRA1 if carts <= 2 else EXTRA2 if carts <= 6 else EXTRA3


@adapts("vector_clocks_crdts", "cluster")
class CartsCluster(ClusterAdapter):
    """The replicas: blue when they hold the same carts as the others, orange the more carts differ,
    red for a moment when an acknowledged add vanished there (or a removed item came back). Gossip
    flies between them in blue; while the network is split it is dropped half way, in red."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.vector_clocks_crdts import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_NODE, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        nodes = [_diverged(k) for k in w.behind_at(run, t)]
        for i in w.wrong_at(run, t):
            nodes[i] = RED
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
        skew = w.skew_at(variant, t)
        words = w.screen.STATES
        if groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            state = (f"{words['partitioned']}  {' | '.join(map(str, sizes))}", RED)
        elif skew is not None:
            state = (w.s("state_skew", node=f"n{skew[0]}", s=skew[1]), ORANGE)
        else:
            state = (words["connected"], GREEN)
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the devices' view

GAUGE_MAX = 200  # messages per second between replicas that fill the gauge
RECENT = 2.0  # seconds a wrong read keeps the state on it


@adapts("vector_clocks_crdts", "lanes")
class CartsLanes(LaneAdapter):
    """The devices' view: adds, removes and reads of their carts, answered by the replica next to
    them (the door, orange while the replicas cannot all talk). A read is green when the cart holds
    what this device put in it, red when one of its adds is missing or an item it removed is back.
    The server's gauge is the gossip between replicas."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.vector_clocks_crdts.scenario import BACK, LOST
        from live.worlds.vector_clocks_crdts import OP_END, OP_OK, OP_START, OP_VERDICT

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return GREEN if o[OP_OK] and o[OP_VERDICT] not in (LOST, BACK) else RED

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                   rare_first=True)
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        recent = [o[OP_VERDICT] for o in run.rows("ops", t - RECENT, t + 1e-9) if o[OP_END] <= t]
        split = w.groups_at(variant, t) is not None
        skew = w.skew_at(variant, t)
        words = w.screen.STATES
        if LOST in recent:
            state = (w.s("lanes_lost"), RED)
        elif BACK in recent:
            state = (w.s("lanes_back"), RED)
        elif split:
            state = (words["partitioned"], ORANGE)
        elif skew is not None:
            state = (w.s("lanes_skew"), ORANGE)
        else:
            state = (words["connected"], GREEN)
        wrong = LOST in recent or BACK in recent
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes,
                         door_color=ORANGE if split else None, fill=fill, gauge=gauge,
                         outline=RED if wrong else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the replicas, and the devices

FLASH = 1.0  # seconds a replica stays red after an add vanished there or a removed item came back


@adapts("vector_clocks_crdts", "peers")
class CartsPeers(PeersAdapter):
    """The devices (the users, and the door: the replica next to them, orange while the replicas cannot all
    talk) and the five replicas on a pentagon. A box's outline is blue while it holds the same carts as the
    others, light to deep orange the more carts differ ("n0 12 differ"), red for a moment when an
    acknowledged add vanished there or a removed item came back; a replica whose clock is off says by how
    much ("n4 clock +5s"). Its gauge is the gossip it sends per second against its share of the 150/s goal. A
    link is drawn while gossip runs along it (blue); a partition cuts every link between the groups (red ✕)
    and drops what is sent across, and once it heals the links light up again with the catching up."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.vector_clocks_crdts.lab import MSGS_MAX, NODES
        from live.worlds.vector_clocks_crdts import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, OP_NODE, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = CartsLanes(w).frame(variant, t, users)  # the devices, the door, the answers and the state
        flights, drops, recent = peer_traffic(run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED),
                                              lambda m: BLUE, most=MAX_FLIGHTS)
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # device requests, from the door to a replica
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        behind = w.behind_at(run, t)
        wrong = w.wrong_at(run, t, FLASH)
        skew = w.skew_at(variant, t)
        sent = sent_per_second(run, t, MSG_SRC)
        share = MSGS_MAX / NODES
        peers = []
        for i, k in enumerate(behind):
            node = f"n{i}"
            colour = RED if i in wrong else _diverged(k)
            if skew is not None and skew[0] == i:
                label = w.s("peer_skew", node=node, s=skew[1])
            elif k:
                label = w.s("peer_differ", node=node, n=k)
            else:
                label = node
            fill = sent.get(i, 0) / share
            peers.append(Leaf(label=(label, colour), short=w.s("peer_differ_short", node=node, n=k) if k else node,
                              tiny=node, fill=min(1.0, fill), gauge=EXTRA2 if fill > 1 else BLUE, outline=colour))
        groups = w.groups_at(variant, t)
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=lane.state, peers=peers,
                          links=link_list(recent, groups, LINE), groups=groups,  # a partition: all its links cut
                          flights=every(flights, MAX_FLIGHTS), drops=drops)
