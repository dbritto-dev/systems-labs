"""The pictures for lab raft_consensus: the peers (five nodes on a pentagon, by role, AppendEntries and votes
between them), the cluster (the same on a grid), and the clients' view (lanes)."""

from __future__ import annotations

from live.adapters.common import (
    client_lanes, every, link_list, message_gauge, peer_gauge, peer_traffic, sent_per_second,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import LINE, Leaf, PeersAdapter, PeersFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80


@adapts("raft_consensus", "cluster")
class RaftCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.raft_consensus.scenario import DOWN, VOTE
        from live.worlds.raft_consensus import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, OP_NODE, OP_START, ROLE_COLOURS, name,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        roles = w.roles_at(variant, t)
        nodes = [ROLE_COLOURS.get(r, BLUE) for r in roles]
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, EXTRA1 if m[MSG_KIND] == VOTE else BLUE))
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client commands on their way
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        groups = w.groups_at(variant, t)
        words = w.screen.STATES
        down = [name(i) for i, r in enumerate(roles) if r == DOWN]
        inc = w.incident_at(variant, t)
        if groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            state = (f"{words['partitioned']}  {' | '.join(map(str, sizes))}", RED)
        elif down:
            state = (f"{words['down']}  {' '.join(down)}", RED)
        elif inc is not None and inc.kind == "slow":
            state = (f"{words['degraded']}  {inc.severity:.0f}x", RED)
        else:
            state = (words["connected"], GREEN)
        return ClusterFrame(nodes=nodes, groups=groups, flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 300  # messages per second between nodes that fill the gauge
RECENT = 2.0  # seconds an answer keeps the state on it (~10 commands/s)
COMMIT_SLACK = 1.0  # seconds after its answer a command must be on a majority (the checker looks every 0.1 s)


@adapts("raft_consensus", "lanes")
class RaftLanes(LaneAdapter):
    """The clients' view: commands through the leader (the door, shut while there is none) to the log
    (the server, its gauge the messages between nodes). An answer is green when acknowledged and committed,
    red when acknowledged but never committed (a lie to the client), orange when the client gave up."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.raft_consensus import INF, OP_END, OP_OK, OP_START, OP_VALUE, _committed, leader_at

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        committed = _committed(run)

        def uncommitted(o) -> bool:
            # Not yet known for an answer too close to the end of what has been simulated.
            seen = o[OP_END] + COMMIT_SLACK <= run.end
            return o[OP_OK] and seen and committed.get(o[OP_VALUE], INF) > o[OP_END] + COMMIT_SLACK

        def colour(o):
            return EXTRA2 if not o[OP_OK] else RED if uncommitted(o) else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour)
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        leader, _ = leader_at(run, t)
        recent = [o for o in run.rows("ops", t - RECENT, t + 1e-9) if o[OP_END] <= t]
        lied = any(uncommitted(o) for o in recent)
        words = w.screen.STATES
        if lied:
            state = (w.s("lanes_uncommitted"), RED)
        elif leader is None:
            state = (w.s("lanes_no_leader"), RED)
        elif any(not o[OP_OK] for o in recent):
            state = (w.s("lanes_unanswered"), EXTRA2)
        elif w.groups_at(variant, t) is not None:
            state = (words["partitioned"], RED)
        else:
            state = (words["connected"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=leader is None, fill=fill,
                         gauge=gauge, outline=RED if lied else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the nodes, and the clients

SENT_MAX = 60  # messages a node sends per second that fill its gauge (a leader sends ~50: heartbeats, entries)


@adapts("raft_consensus", "peers")
class RaftPeers(PeersAdapter):
    """The clients (the users and the door, as in lanes: shut while there is no leader) and the five nodes on
    a pentagon, outlined by role (green leader, orange candidate, blue follower, grey down), its term under
    its name ("n3" / "t4"), its gauge the messages it sends per second. A link is drawn while it
    carries messages: blue AppendEntries, light orange RequestVote. During a partition every link between the
    two sides is drawn and cut (a red ✕): a stale leader cut off on the minority side shows as a second
    "leader" whose links are all cut, its AppendEntries lost half way."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.raft_consensus.scenario import DOWN, VOTE
        from live.worlds.raft_consensus import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, OP_NODE, OP_START, ROLE_COLOURS, ST_TERMS, name,
            state_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = RaftLanes(w).frame(variant, t, users)  # the users, the door, the answers and the state
        row = state_at(run, t)
        roles = w.roles_at(variant, t)
        terms = row[ST_TERMS] if row else (0,) * len(roles)
        flights, drops, recent = peer_traffic(run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED),
                                              lambda m: EXTRA1 if m[MSG_KIND] == VOTE else BLUE, most=MAX_FLIGHTS)
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client commands, from the door to a node
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        groups = w.groups_at(variant, t)
        sent = sent_per_second(run, t, MSG_SRC)
        peers = []
        for i, role in enumerate(roles):
            node, term = name(i), terms[i] if i < len(terms) else 0
            # The colour says the role (the legend); the words only the term, under the name.
            label = w.s("peer_term", node=node, term=term) if term and role != DOWN else node
            colour = ROLE_COLOURS.get(role, BLUE)
            fill, gauge = peer_gauge(sent.get(i, 0) / SENT_MAX)
            peers.append(Leaf(label=(label, MUTED if role == DOWN else colour),
                              short=node, tiny=node, fill=0.0 if role == DOWN else fill, gauge=gauge, outline=colour))
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=lane.state, peers=peers,
                          links=link_list(recent, groups, LINE), groups=groups,  # a partition: all its links cut
                          flights=every(flights, MAX_FLIGHTS), drops=drops)
