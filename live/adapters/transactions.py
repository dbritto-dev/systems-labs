"""The pictures for lab transactions: the three nodes (peers: in a column, the links between them; cluster: on
a grid), and the clients' view (lanes)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, link_list, message_gauge, peer_traffic
from live.canvas import BLUE, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import LINE, Leaf, PeersAdapter, PeersFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 60


@adapts("transactions", "cluster")
class TxnCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.transactions.scenario import TXN_NODE, TXN_START
        from live.worlds.transactions import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC

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

GAUGE_MAX = 300  # messages per second between nodes that fill the cluster's gauge


@adapts("transactions", "lanes")
class TxnLanes(LaneAdapter):
    """The clients' view: transactions waiting on the cluster; the door is the network."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.transactions.scenario import TXN_BAD, TXN_END, TXN_OK, TXN_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "txns", TXN_START, TXN_END,
                                                   lambda o: not o[TXN_OK] or o[TXN_BAD])
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        split = w.cut_at(variant, t) is not None
        seen = w.anomalies_at(run, t, 1.0)
        g1b = bool(seen)
        words = w.screen.STATES
        if seen:
            state = (w.s("lanes_" + sorted(seen.values())[-1].lower()), RED)
        elif split:
            state = (words["partitioned"], RED)
        else:
            state = (words["connected"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=split, fill=fill, gauge=gauge,
                         outline=RED if split or g1b else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the column, and the clients


@adapts("transactions", "peers")
class TxnPeers(PeersAdapter):
    """The clients (the users, and the door: the network, shut while a node is cut off; an answer is green, red
    when it failed or read an uncommitted write) and the three nodes in a column, every line straight: a level line from the door to each, a vertical
    line between neighbours, a bracket right of them between n0 and n2. A box's outline is how up to
    date it is: blue, oranges the more keys it is behind, red for a moment when it served an intermediate read
    ("n1 G1b"), or showed a dirty write ("n1 G0"). Its gauge is its share of fresh keys (within 1 s of the newest value; orange under 95%). A link
    is drawn while it carries replication (blue); the two links of a node cut off are cut (a red ✕, "n2 cut
    off"), what is sent over them lost half way; the re-sends that piled up flow once it heals."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.transactions import lab
        from labs.transactions.scenario import TXN_NODE, TXN_START
        from live.worlds.transactions import MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = TxnLanes(w).frame(variant, t, users)  # the users, the door, the answers and the state
        flights, drops, recent = peer_traffic(run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED), lambda m: BLUE,
                                              most=MAX_FLIGHTS)
        for r in run.rows("txns", t - 0.12, t + 1e-9):  # transactions on their way (~100 ms)
            flights.append((-1, r[TXN_NODE], min(1.0, (t - r[TXN_START]) / 0.1), WHITE))
        cut = w.cut_at(variant, t)
        stale = w.stale_at(run, t)
        groups = None if cut is None else [1 if i == cut else 0 for i in range(len(stale))]
        g1b = w.anomalies_at(run, t, 0.5)
        colours = w.node_colours(run, t)
        peers = []
        for i, behind in enumerate(stale):
            node = f"n{i}"
            if i in g1b:
                label = w.s("peer_anomaly", node=i, kind=g1b[i])
            elif i == cut:
                label = w.s("state_cut", node=i)
            else:
                label = node
            fresh = 1 - behind / lab.KEYS
            peers.append(Leaf(label=(label, RED if i == cut else colours[i]), short=node, tiny=node, fill=fresh,
                              gauge=BLUE if fresh >= lab.FRESH_MIN else EXTRA2, outline=colours[i]))
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=lane.state, peers=peers,
                          links=link_list(recent, groups, LINE), groups=groups,  # its two links cut
                          flights=every(flights, MAX_FLIGHTS), drops=drops, column=True)
