"""The pictures for lab deadline_propagation: lanes (users → the gateway door → the chain, with the
db's connections as the gauge) and cluster (the chain gateway → api → orders → db, calls flying)."""

from __future__ import annotations

from labs.deadline_propagation.scenario import CALL_OK, HOPS, OK
from live.adapters.common import BACK, FLIGHTS, FLY, every, just_ended, just_sent, user_flights, user_outcomes
from live.canvas import BLUE, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

LONG_WAIT = 1.0  # a user who has waited this long turns orange: about to give up


def _state(w, run, t: float, inc) -> tuple[str, tuple[int, int, int]]:
    """The words and colour under the picture: the db's connections and how many work for nobody."""
    words = w.screen.STATES
    live, dead = w.db_busy(run, t)
    if dead:
        return f"{words['degraded']} · {w.s('state_dead', dead=dead, n=w.connections)}", RED
    if inc is not None:
        return words["degraded"], EXTRA2
    return words["healthy"], GREEN


@adapts("deadline_propagation", "lanes")
class DeadlinePropagationLanes(LaneAdapter):
    """Users wait at the gateway; a user who gave up turns into a red ring while the chain still
    works on their request. The gauge is the db's connections: red while they run queries for
    users who already left."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.deadline_propagation import (
            REQ_END, REQ_ID, REQ_OUTCOME, REQ_START, W_REQ, W_FREED, left_by,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        # Users who left while the chain still works on their request: a red ring.
        found = {}
        for row in run.active("work", t, W_FREED):
            if left_by(row, t):
                found[slot(row[W_REQ], users)] = (RED, False)
        # Users still waiting: white, orange once they are about to give up.
        for r in run.active("requests", t, REQ_END):
            found[slot(r[REQ_ID], users)] = (EXTRA2 if t - r[REQ_START] >= LONG_WAIT else WHITE, True)

        flying = just_sent(run, "requests", t)
        flights = user_flights(every(flying, FLIGHTS), t, REQ_START, lambda r: (slot(r[REQ_ID], users), WHITE, False))
        span = run.max_dur.get("requests", 0.0)
        ended = just_ended(run, "requests", REQ_END, t)
        outcomes = user_outcomes(ended, t, REQ_END, lambda r: GREEN if r[REQ_OUTCOME] == OK else RED)
        # The door (the gateway) turns orange while many answers in the last second were not served.
        last = [r for r in ended if t - 1.0 <= r[REQ_END]] or [
            r for r in run.rows("requests", t - 1.0 - span, t) if t - 1.0 <= r[REQ_END] < t]
        bad = sum(r[REQ_OUTCOME] != OK for r in last) / len(last) if len(last) >= 5 else 0.0
        door = EXTRA2 if bad >= 0.3 else None

        inc = w.incident_at(variant, t)
        live, dead = w.db_busy(run, t)
        n = max(1, w.connections)
        gauge = RED if dead * 2 >= max(1, live + dead) and dead else EXTRA2 if dead else BLUE
        outline = EXTRA2 if inc is not None else OUTLINE
        return LaneFrame(users=found, flights=flights, outcomes=outcomes, closed=False, door_color=door,
                         fill=(live + dead) / n, gauge=gauge, outline=outline, state=_state(w, run, t, inc))


@adapts("deadline_propagation", "cluster")
class DeadlinePropagationCluster(ClusterAdapter):
    """The chain, live: clients → gateway → api → orders → db (a 2x2 grid, read like a Z).

    Requests fly from the clients to the gateway; calls fly from each service to the next and park
    near the callee while the caller waits. A call whose user has already left is red: work and
    waiting for nobody. Calls cut short by a timeout, or that fail, die in red on their edge; users
    who give up die on the way in.
    """

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.deadline_propagation import (
            C_END, C_GONE, C_HOP, C_OUTCOME, C_START, REQ_END, REQ_OUTCOME, REQ_START,
        )
        from labs.deadline_propagation.scenario import GAVE_UP

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = [(-1, 0, (t - r[REQ_START]) / FLY, WHITE)
                   for r in every(just_sent(run, "requests", t), FLIGHTS // 2)]
        span = run.max_dur.get("calls", 0.0)
        calls = [c for c in run.rows("calls", t - span - 1e-9, t + 1e-9)
                 if c[C_START] >= t - FLY or c[C_END] > t]
        dead = [c for c in calls if c[C_GONE] is not None and c[C_GONE] <= t]
        live = [c for c in calls if not (c[C_GONE] is not None and c[C_GONE] <= t)]
        for colour, rows in ((WHITE, live), (RED, dead)):
            for c in every(rows, FLIGHTS):
                flights.append((c[C_HOP], c[C_HOP] + 1, min(0.95, (t - c[C_START]) / FLY), colour))

        drops = []
        for c in run.rows("calls", t - BACK - span, t + 1e-9):
            if t - BACK <= c[C_END] <= t and c[C_OUTCOME] != CALL_OK:
                drops.append((c[C_HOP], c[C_HOP] + 1, (t - c[C_END]) / BACK))
        rspan = run.max_dur.get("requests", 0.0)
        for r in run.rows("requests", t - BACK - rspan, t + 1e-9):
            if t - BACK <= r[REQ_END] <= t and r[REQ_OUTCOME] == GAVE_UP:
                drops.append((-1, 0, (t - r[REQ_END]) / BACK))

        inc = w.incident_at(variant, t)
        nodes = []
        for k, (working, queued, gone) in enumerate(w.at_hops(run, t)):
            if gone and gone * 2 >= working + queued + gone:
                nodes.append(RED)  # most of its workers wait or work for users who left
            elif gone or (k == len(HOPS) - 1 and inc is not None):
                nodes.append(EXTRA2)
            else:
                nodes.append(BLUE)
        text, colour = _state(w, run, t, inc)
        chain = " → ".join(w.hop_name(k) for k in range(len(HOPS)))
        return ClusterFrame(nodes=nodes, flights=flights, drops=every(drops, 30),
                            state=(f"{text}   {chain}", colour))
