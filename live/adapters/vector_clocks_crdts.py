"""The pictures for lab vector_clocks_crdts: the replicas gossiping, and the devices reading their carts."""

from __future__ import annotations

from live.adapters.common import client_lanes, every, message_gauge
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

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
