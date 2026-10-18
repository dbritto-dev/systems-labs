"""The pictures for lab failure_detection: the nodes as the cluster sees them (peers: on an octagon, the links
that carried messages; cluster: on a grid), and the clients' view (lanes)."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge, peer_traffic, sent_per_second
from live.canvas import BG, BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, ORANGE, PINK, RED, WHITE, mix
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import Leaf, PeersAdapter, PeersFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80
RECENT = 5.0  # seconds a false death keeps the state on it


def _sick_state(w, inc, crashed: bool) -> tuple[str, tuple[int, int, int]]:
    """The incident going on, in a few words: DOWN: n2, DEGRADED: n3, LOSSY: n5, PARTITIONED: n4."""
    from live.worlds.failure_detection import name

    node = name(w.victims.get(inc.t0, 0))
    words = w.screen.STATES
    if inc.kind == "crash":
        return w.s("state_sick", state=words["down"], node=node), RED if crashed else ORANGE
    if inc.kind == "partial":
        return w.s("state_sick", state=words["partitioned"], node=node), ORANGE
    if inc.kind == "lossy":
        return w.s("state_sick", state=w.s("state_lossy"), node=node), ORANGE
    return w.s("state_sick", state=words["degraded"], node=node), ORANGE


@adapts("failure_detection", "cluster")
class FailureCluster(ClusterAdapter):
    """Each node in the colour the cluster gives it: blue alive, orange suspected, red declared dead; grey
    when it has crashed but nobody has noticed yet. Probes fly in blue, indirect probes (ping_req) in light
    orange; a message lost on a flaky link, a lossy node or a cut stops half way in red."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.failure_detection.scenario import DEAD, SUSPECT
        from live.worlds.failure_detection import (
            DEATH_FALSE, DEATH_PEER, MSG_ARRIVED, MSG_DEST, MSG_INDIRECT, MSG_SENT, MSG_SRC, REQ_NODE,
            REQ_START, VIEW_CRASHED, VIEW_MARKS, name, view_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        from labs.failure_detection.lab import NODES

        view = view_at(run, t)
        marks = view[VIEW_MARKS] if view else (0,) * NODES
        crashed = view[VIEW_CRASHED] if view else 0
        nodes = []
        for i, m in enumerate(marks):
            if m == DEAD:
                nodes.append(RED if crashed >> i & 1 else PINK)  # declared dead: really, or alive (pink)
            elif crashed >> i & 1:
                nodes.append(MUTED)  # down, and the cluster has not noticed yet
            else:
                nodes.append(ORANGE if m == SUSPECT else BLUE)
        flights, drops = [], []
        for m in run.rows("msgs", t - 2.0, t + 1e-9):  # a slow node's messages take a few times longer
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                if t - m[MSG_SENT] < DROP_FADE:
                    drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                flights.append((m[MSG_SRC], m[MSG_DEST], p, EXTRA1 if m[MSG_INDIRECT] else BLUE))
        for r in run.rows("reqs", t - 0.06, t + 1e-9):  # client requests on their way
            flights.append((-1, r[REQ_NODE], min(1.0, (t - r[REQ_START]) / 0.05), WHITE))
        inc = w.incident_at(variant, t)
        wrong = [d for d in run.rows("deaths", t - RECENT, t + 1e-9) if d[DEATH_FALSE]]
        if wrong:
            state = (w.s("state_false", node=name(wrong[-1][DEATH_PEER])), RED)
        elif inc is not None:
            v = w.victims.get(inc.t0, 0)
            state = _sick_state(w, inc, marks[v] == DEAD)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 120  # messages per second between nodes that fill the gauge
RECENT_ANSWER = 1.5  # seconds an answer keeps the state on it (~30 requests/s)


@adapts("failure_detection", "lanes")
class FailureLanes(LaneAdapter):
    """The clients' view: requests through the router (the door: orange while it avoids a node, red while it
    still sends to a crashed one) to the cluster (the server, its gauge the messages between nodes). Each
    session has a home node: an answer is green from it, light orange when failed over because the home node
    really is dead, deep orange when failed over because a healthy node was declared dead (needless), and red
    when the home node had crashed and the router did not know yet."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.failure_detection.scenario import DEAD, FAILED, FAILOVER, NEEDLESS
        from live.worlds.failure_detection import REQ_END, REQ_OUTCOME, REQ_START, VIEW_CRASHED, VIEW_MARKS, view_at

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        colours = {FAILED: RED, FAILOVER: EXTRA1, NEEDLESS: EXTRA3}

        def colour(r):
            return colours.get(r[REQ_OUTCOME], GREEN)

        waiting, flights, outcomes = client_lanes(run, t, users, "reqs", REQ_START, REQ_END, colour=colour,
                                                   rare_first=True)
        fill, gauge = message_gauge(run, t, GAUGE_MAX)
        view = view_at(run, t)
        marks = view[VIEW_MARKS] if view else ()
        crashed = view[VIEW_CRASHED] if view else 0
        out = sum(1 for m in marks if m == DEAD)
        unseen = any(crashed >> i & 1 and m != DEAD for i, m in enumerate(marks))
        recent = [r for r in run.rows("reqs", t - RECENT_ANSWER - 1.0, t + 1e-9) if t - RECENT_ANSWER <= r[REQ_END] <= t]
        kinds = {r[REQ_OUTCOME] for r in recent}
        door = RED if unseen else ORANGE if out else None
        if FAILED in kinds:
            state = (w.s("lanes_failing"), RED)
        elif NEEDLESS in kinds:
            state = (w.s("lanes_needless"), EXTRA3)
        elif out:
            state = (w.s("lanes_in_use", n=len(marks) - out, of=len(marks)), EXTRA2)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=door, fill=fill,
                         gauge=gauge, outline=RED if unseen else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the octagon, and the clients

FLAKY_LINK = mix(ORANGE, BG, 0.45)  # the links through the old switch, always drawn: dim orange
MOST_LINKS = 8  # links drawn besides the flaky ones (the latest to carry a message): never the whole mesh


@adapts("failure_detection", "peers")
class FailurePeers(PeersAdapter):
    """The clients (the users, and the door: their router, orange while it avoids a node, red while it still
    sends to a crashed one) and the eight nodes on an octagon. A box's outline is the cluster's view of that
    node: blue alive, orange suspected, red declared dead, pink declared dead but alive, grey crashed and not
    seen yet; under it, just its name. Its gauge is the messages it
    sends per second against the 10/s goal (full and orange past it). The 4 flaky links are always drawn in
    dim orange; the others while they carry a probe (blue), or a ping_req's two hops (light orange); a
    message lost on the way stops short, red."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.failure_detection.lab import MSGS_MAX, NODES
        from labs.failure_detection.scenario import DEAD, FLAKY, SUSPECT
        from live.worlds.failure_detection import (
            MSG_ARRIVED, MSG_DEST, MSG_INDIRECT, MSG_SENT, MSG_SRC, REQ_NODE, REQ_START, VIEW_CRASHED, VIEW_MARKS,
            name, view_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = FailureLanes(w).frame(variant, t, users)  # the users, the router, the answers and the state
        view = view_at(run, t)
        marks = view[VIEW_MARKS] if view else (0,) * NODES
        crashed = view[VIEW_CRASHED] if view else 0
        flights, drops, recent = peer_traffic(run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED),
                                              lambda m: EXTRA1 if m[MSG_INDIRECT] else BLUE, longest=2.0,
                                              most=MAX_FLIGHTS)  # a slow node's messages take longer
        for r in run.rows("reqs", t - 0.06, t + 1e-9):  # client requests, from the router to a node
            flights.append((-1, r[REQ_NODE], min(1.0, (t - r[REQ_START]) / 0.05), WHITE))
        links = {tuple(sorted(f)): FLAKY_LINK for f in FLAKY}
        latest = list(recent.items())[-MOST_LINKS:]  # in the order they were last used: the latest last
        links.update(latest)
        sent = sent_per_second(run, t, MSG_SRC)
        peers = []
        for i, m in enumerate(marks):
            node, down = name(i), bool(crashed >> i & 1)
            # The colour says it all (the legend): dead red, declared dead but alive pink, crashed and not
            # seen yet grey, suspected orange, alive blue; the label is just the name.
            if m == DEAD:
                colour = RED if down else PINK
            elif down:
                colour = MUTED
            else:
                colour = ORANGE if m == SUSPECT else BLUE
            label = node
            k = sent.get(i, 0) / MSGS_MAX
            peers.append(Leaf(label=(label, colour), short=node, tiny=node, fill=min(1.0, k),
                              gauge=EXTRA2 if k > 1 else BLUE, outline=colour))
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=lane.state, peers=peers,
                          links=[(a, b, c) for (a, b), c in sorted(links.items())],
                          flights=every(flights, MAX_FLIGHTS), drops=every(drops, MOST_LINKS))
