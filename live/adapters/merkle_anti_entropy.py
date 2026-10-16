"""The pictures for lab merkle_anti_entropy: the replicas drifting apart and repairing (peers: on a square, the
links between them; cluster: on a grid), and the clients' reads (lanes)."""

from __future__ import annotations

from live.adapters.common import LINK_RECENT, client_lanes, every, link_list, peer_traffic
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import LINE, Leaf, PeersAdapter, PeersFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80
MAX_CLIENTS = 8  # client requests shown at once (a sample: there are ~300 a second)
CLIENT_FLY = 0.1  # seconds a client request takes to reach its replica (cosmetic)


def _repair_colour(entries: int):
    """A repair message, by what it carries: a few hashes, a leaf's keys, or a whole key range."""
    return EXTRA1 if entries <= 50 else EXTRA2 if entries <= 2_000 else EXTRA3


@adapts("merkle_anti_entropy", "cluster")
class MerkleCluster(ClusterAdapter):
    """The replicas: blue when they hold the latest version of every key, deeper orange the more keys
    they miss, red while down. Replication batches fly between them in blue, repair messages in orange
    (deeper the more entries they carry: a full scan is a deep orange stream); while a replica is cut
    off, messages to and from it are dropped half way, in red. Client reads and writes come in white."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.merkle_anti_entropy import (MSG_ARRIVED, MSG_DEST, MSG_ENTRIES, MSG_REPAIR, MSG_SENT,
                                                    MSG_SRC, OP_NODE, OP_START, diverged_at, shade)

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        diverged = diverged_at(run, t)
        nodes = [shade(k) for k in diverged]
        cut = w.cut_at(variant, t)
        if cut is not None and cut[0] == "down":
            nodes[cut[1]] = RED
        repair, replication, drops = [], [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                if m[MSG_REPAIR]:
                    repair.append((m[MSG_SRC], m[MSG_DEST], p, _repair_colour(m[MSG_ENTRIES])))
                else:
                    replication.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        clients = [(-1, o[OP_NODE], (t - o[OP_START]) / CLIENT_FLY, WHITE)
                   for o in run.rows("ops", t - CLIENT_FLY, t + 1e-9)]
        flights = repair[:MAX_FLIGHTS // 2]  # repair first: it is the lesson
        flights += every(replication, (MAX_FLIGHTS - len(flights)) // 2)
        flights += every(clients, min(MAX_CLIENTS, MAX_FLIGHTS - len(flights)))
        groups = None if cut is None else [0 if i == cut[1] else 1 for i in range(len(nodes))]
        return ClusterFrame(nodes=nodes, groups=groups, flights=flights, drops=every(drops, 30),
                            state=_replicas_state(w, cut, sum(diverged)))


def _replicas_state(w, cut, total: int) -> tuple:
    """The words under the replicas: one down or cut off, how many keys differ, or in sync."""
    if cut is not None:
        word = w.s("state_down", node=f"n{cut[1]}") if cut[0] == "down" else w.screen.STATES["partitioned"]
        return word, RED
    if total:
        return w.s("state_diverged", n=total), ORANGE
    return w.s("state_sync"), GREEN


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 20_000  # repair entries per second that fill the gauge
RECENT = 2.0  # seconds a stale read keeps the state on it


@adapts("merkle_anti_entropy", "lanes")
class MerkleLanes(LaneAdapter):
    """The clients' view: reads and writes, each answered by one replica (the door, orange while some
    replica holds older versions). A read is green when it got the latest version, red when it got an
    older one (a stale read). The server's gauge is the repair traffic: full in a full scan."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.merkle_anti_entropy import OP_END, OP_STALE, OP_START, diverged_at

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return RED if o[OP_STALE] else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                   rare_first=True)
        s = int(t)
        sent = sum(run.series("repair", s - 1, s))
        fill = min(1.0, sent / GAUGE_MAX)
        stale = any(o[OP_STALE] for o in run.rows("ops", t - RECENT, t + 1e-9) if o[OP_END] <= t)
        total = sum(diverged_at(run, t))
        cut = w.cut_at(variant, t)
        if stale:
            state = (w.s("lanes_stale"), RED)
        elif cut is not None and cut[0] == "down":
            state = (w.screen.STATES["degraded"], ORANGE)
        elif total:
            state = (w.s("lanes_diverged"), ORANGE)
        else:
            state = (w.s("lanes_sync"), GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes,
                         door_color=ORANGE if total else None, fill=fill,
                         gauge=EXTRA2 if fill > 0.5 else BLUE, outline=RED if stale else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the square, and the clients

WHOLE_RANGE = 5_000  # entries past which a repair message is a key range, not a few leaves: deep orange


def _link_repair_colour(entries: int):
    """A repair message on a link: light a few hashes, mid a few leaves' keys (a Merkle walk sends a few
    thousand at most), deep a whole range or more (a full scan sends all 20,000 versions every round)."""
    return EXTRA1 if entries <= 50 else EXTRA2 if entries <= WHOLE_RANGE else EXTRA3


@adapts("merkle_anti_entropy", "peers")
class MerklePeers(PeersAdapter):
    """The clients (the users, and the door: orange while some replica holds older versions; a read is green
    fresh, red stale) and the four replicas on a square (standing on a corner). A box's outline is what it misses: blue when it holds
    the latest of every key, deeper orange the more keys it lacks ("n1 −340"), red while down ("n2 down"). Its
    gauge is the hashing it does a second against the 10,000 goal (orange past it). A link is drawn while it
    carries something: blue replication batches, orange repair (deeper the more entries a message carries: a
    full scan is a deep orange stream, a Merkle walk a short, lighter burst). The links of a replica
    that is down or cut off are cut (a red ✕), what is sent over them lost half way."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.merkle_anti_entropy import lab
        from live.worlds.merkle_anti_entropy import (MSG_ARRIVED, MSG_DEST, MSG_ENTRIES, MSG_REPAIR, MSG_SENT,
                                                    MSG_SRC, OP_NODE, OP_START, diverged_at, shade)

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = MerkleLanes(w).frame(variant, t, users)  # the users, the door, the answers
        diverged = diverged_at(run, t)
        cut = w.cut_at(variant, t)
        flights, drops, recent = peer_traffic(
            run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED),
            lambda m: _link_repair_colour(m[MSG_ENTRIES]) if m[MSG_REPAIR] else BLUE, most=10_000)
        depth = (EXTRA1, EXTRA2, EXTRA3)
        for m in run.rows("msgs", t - LINK_RECENT, t + 1e-9):  # a link that carried repair shows it, deepest
            if m[MSG_REPAIR]:
                key = (min(m[MSG_SRC], m[MSG_DEST]), max(m[MSG_SRC], m[MSG_DEST]))
                c = _link_repair_colour(m[MSG_ENTRIES])
                if recent.get(key) not in depth or depth.index(recent[key]) < depth.index(c):
                    recent[key] = c
        repair = [f for f in flights if f[3] != BLUE]
        shown = every(repair, MAX_FLIGHTS // 2)  # repair first: it is the lesson
        shown += every([f for f in flights if f[3] == BLUE], (MAX_FLIGHTS - len(shown)) // 2)
        clients = [(-1, o[OP_NODE], (t - o[OP_START]) / CLIENT_FLY, WHITE)
                   for o in run.rows("ops", t - CLIENT_FLY, t + 1e-9)]
        shown += every(clients, min(MAX_CLIENTS, MAX_FLIGHTS - len(shown)))
        groups = None if cut is None else [0 if i == cut[1] else 1 for i in range(len(diverged))]
        stale = lane.state[0] == w.s("lanes_stale")  # a stale read just now: the clients see it
        state = lane.state if stale else _replicas_state(w, cut, sum(diverged))
        s = int(t)
        peers = []
        for i, keys in enumerate(diverged):
            node = f"n{i}"
            colour = shade(keys)
            if cut is not None and cut[1] == i:
                down = cut[0] == "down"
                colour = RED if down else colour
                label, words = w.s("peer_down" if down else "peer_cut", node=node), RED
            elif keys:
                label, words = w.s("peer_missing", node=node, n=keys), colour
            else:
                label, words = node, colour
            k = sum(run.series(f"hash{i}", s - 1, s)) / lab.HASH_MAX
            peers.append(Leaf(label=(label, words), short=node, tiny=node, fill=min(1.0, k),
                              gauge=EXTRA2 if k > 1 else BLUE, outline=colour))
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=state, peers=peers,
                          links=link_list(recent, groups, LINE), groups=groups, flights=shown, drops=drops)
