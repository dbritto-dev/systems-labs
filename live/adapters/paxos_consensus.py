"""The pictures for lab paxos_consensus: cluster (the nodes, the leader in green, and the propose /
prepare / promise / accept / decide messages between them) and lanes (the clients' view)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

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
