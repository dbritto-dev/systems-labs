"""The pictures for lab paxos_consensus: peers (the five nodes on a pentagon, the leader in green, and the
propose / prepare / promise / accept / decide messages between them), cluster (the same on a grid) and lanes
(the clients' view)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, link_list, message_gauge, peer_traffic
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import LINE, Leaf, PeersAdapter, PeersFrame

DROP_FADE = 0.6  # seconds a lost message stays on screen
MAX_FLIGHTS = 80


def colours():
    from labs.paxos_consensus.scenario import ACCEPT, ACCEPTED, DECIDE, PREPARE, PROMISE, PROPOSE

    return {PROPOSE: PURPLE, PREPARE: EXTRA1, PROMISE: EXTRA1, ACCEPT: BLUE, ACCEPTED: BLUE, DECIDE: GREEN}


def cluster_state(w, variant: str, t: float, roles) -> tuple[str, tuple[int, int, int]]:
    """The words under the grid, and their colour."""
    from labs.paxos_consensus.scenario import DOWN, PAUSED
    from live.worlds.paxos_consensus import name

    words = w.screen.STATES
    groups = w.groups_at(variant, t)
    down = [name(i) for i, r in enumerate(roles) if r == DOWN]
    paused = [name(i) for i, r in enumerate(roles) if r == PAUSED]
    inc = w.incident_at(variant, t)
    if groups is not None:
        sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
        return f"{words['partitioned']}  {' | '.join(map(str, sizes))}", RED
    if down:
        return f"{words['down']}  {' '.join(down)}", RED
    if paused:
        return w.s("state_paused", node=paused[0]), EXTRA2
    if inc is not None and inc.kind == "lossy":
        return w.s("state_lossy", pct=round(inc.severity * 100)), RED
    return words["connected"], GREEN


@adapts("paxos_consensus", "cluster")
class PaxosCluster(ClusterAdapter):
    """Nodes: green the leader, blue the others, orange a candidate, deep orange paused, grey down, red
    for 2 s once it decided a command another node decided differently in that slot. Messages fly at
    their real speed: purple propose (stage 0), light orange prepare/promise (phase 1), blue
    accept/accepted (phase 2), green decide, grey the rest (heartbeats, catch-up); a lost one stops
    half way and fades in red. Client commands fly in white from the left."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.paxos_consensus import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, OP_NODE, OP_START, ROLE_COLOURS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        roles = w.roles_at(variant, t)
        split = w.split_nodes(run, t)
        nodes = [RED if i in split else ROLE_COLOURS.get(r, BLUE) for i, r in enumerate(roles)]
        kinds = colours()
        flights, drops = [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, kinds.get(m[MSG_KIND], MUTED)))
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client commands on their way
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        return ClusterFrame(nodes=nodes, groups=w.groups_at(variant, t), flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=cluster_state(w, variant, t, roles))


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 300  # messages per second between nodes that fill the gauge
STALL = 1.0  # seconds with clients waiting and no answer: the door shuts


@adapts("paxos_consensus", "lanes")
class PaxosLanes(LaneAdapter):
    """The clients' view: commands to the cluster (the door, shut while clients wait and nothing has
    been decided for a second) and the log (the server, its gauge the messages between nodes). An
    answer is green when it is in the log the nodes agree on, red when answered but lost (another
    command won its slot), orange when the client gave up after 2 s."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.paxos_consensus import OP_END, OP_KEPT, OP_OK, OP_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return EXTRA2 if not o[OP_OK] else RED if not o[OP_KEPT] else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                  rare_first=True)
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        longest = run.max_dur.get("ops", 0.0)
        answered = any(o[OP_OK] and t - STALL <= o[OP_END] <= t
                       for o in run.rows("ops", t - STALL - longest, t + 1e-9))
        stalled = bool(run.active("ops", t, OP_END)) and not answered and t >= STALL
        lost = w.lost_recently(run, t)
        split = bool(w.split_nodes(run, t))
        if lost:
            state = (w.s("lanes_lost"), RED)
        elif split:
            state = (w.s("lanes_split"), RED)
        elif stalled:
            state = (w.s("lanes_stalled"), RED)
        elif w.groups_at(variant, t) is not None:
            state = (w.screen.STATES["partitioned"], RED)
        else:
            state = (w.screen.STATES["connected"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=stalled, fill=fill,
                         gauge=gauge, outline=RED if lost or split else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the nodes, and the clients

BEHIND = 5  # slots a node may be behind the furthest one before its gauge turns orange


@adapts("paxos_consensus", "peers")
class PaxosPeers(PeersAdapter):
    """The clients (the users and the door, as in lanes: shut while they wait and nothing is decided) and the
    five nodes on a pentagon. Outline: green the leader, orange a candidate, deep orange paused, grey down,
    blue the others, red for 2 s once it decided a slot differently from another node. Each is named with its
    role and ballot ("n2 leader b7"); its gauge is the slots it has decided against the furthest node (orange
    when it is behind). A link is drawn while it carries messages, in the colour of the latest: purple
    propose, light orange prepare/promise, blue accept, green decide; a lost one stops short, in red; a
    partition cuts every link between the two sides."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.paxos_consensus.scenario import DOWN
        from live.worlds.paxos_consensus import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, OP_NODE, OP_START, ROLE_COLOURS, ST_BALLOTS,
            ST_DECIDED, name, state_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = PaxosLanes(w).frame(variant, t, users)  # the users, the door, the answers and the state
        roles = w.roles_at(variant, t)
        row = state_at(run, t)
        ballots = row[ST_BALLOTS] if row else (0,) * len(roles)
        decided = row[ST_DECIDED] if row else (0,) * len(roles)
        top = max(decided, default=0)
        split = w.split_nodes(run, t)
        kinds = colours()
        flights, drops, recent = peer_traffic(run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED),
                                              lambda m: kinds.get(m[MSG_KIND], MUTED), most=MAX_FLIGHTS)
        for o in run.rows("ops", t - 0.12, t + 1e-9):  # client commands, from the door to a node
            flights.append((-1, o[OP_NODE], min(1.0, (t - o[OP_START]) / 0.1), WHITE))
        peers = []
        for i, role in enumerate(roles):
            node, ballot = name(i), ballots[i] if i < len(ballots) else 0
            # The colour says the role (leader, candidate, down, paused, decided differently: the legend); the
            # words only the ballot, under the name.
            label = w.s("peer_ballot", node=node, ballot=ballot) if ballot and role != DOWN else node
            colour = RED if i in split else ROLE_COLOURS.get(role, BLUE)
            mine = decided[i] if i < len(decided) else 0
            peers.append(Leaf(label=(label, MUTED if role == DOWN and i not in split else colour),
                              short=node, tiny=node,
                              fill=mine / top if top else 0.0, gauge=EXTRA2 if top - mine > BEHIND else BLUE,
                              outline=colour))
        groups = w.groups_at(variant, t)
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=lane.state, peers=peers,
                          links=link_list(recent, groups, LINE), groups=groups,  # a partition: all its links cut
                          flights=every(flights, MAX_FLIGHTS), drops=drops)
