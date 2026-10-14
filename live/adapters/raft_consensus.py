"""The pictures for lab raft_consensus: nodes coloured by role, AppendEntries and votes in flight; and the
clients' view."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

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
