"""The pictures for lab hedged_requests: cluster (the service and its 3 replicas, copies flying to a
second replica) and lanes (users waiting; the door is the hedge budget in front of the replicas)."""

from __future__ import annotations

from labs.hedged_requests.scenario import OK, REPLICAS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


def _load_colour(extra: float | None):
    """The service's (and the gauge's) colour by the extra load copies add."""
    from labs.hedged_requests import lab

    if extra is None or extra <= lab.EXTRA_MAX:
        return BLUE
    return EXTRA2 if extra <= 5 * lab.EXTRA_MAX else RED


def _state(w, variant: str, t: float, extra: float | None):
    """The words under the picture: healthy, degraded (an incident), busy (copies add a lot of load)."""
    from labs.hedged_requests import lab

    inc = w.incident_at(variant, t)
    words = w.screen.STATES
    if extra is not None and extra > 2 * lab.EXTRA_MAX:
        return words["busy"], EXTRA2 if extra <= 5 * lab.EXTRA_MAX else RED
    if inc is not None:
        return words["degraded"], EXTRA2
    return words["healthy"], GREEN


@adapts("hedged_requests", "cluster")
class HedgedRequestsCluster(ClusterAdapter):
    """The service (the Client lives there) and its 3 replicas, live.

    Reads fly from the clients to the service; calls fly from the service to a replica: white for
    the first call, orange for a copy (a hedge). A call that takes long parks by its replica: light
    orange while its read still waits for it, deep orange once the read was answered by the other
    copy and nobody cancelled it (wasted work). A slow replica turns orange. Users who give up die
    in red on the way in.
    """

    SERVICE = 0

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.hedged_requests import (
            CALL_COPY, CALL_END, CALL_REPLICA, CALL_START, REQ_END, REQ_OUTCOME, REQ_START, SLOW,
            _slow_replicas,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = [(-1, self.SERVICE, (t - r[REQ_START]) / FLY, WHITE)
                   for r in every(run.rows("requests", t - FLY, t + 1e-9), FLIGHTS // 2)]
        # When each read still running or just answered was answered (to tell waiting calls from waste).
        span = run.max_dur.get("calls", 0.0)
        rspan = run.max_dur.get("requests", 0.0)
        reads = run.rows("requests", t - span - rspan - 1e-9, t + 1e-9)
        answered = {r[0]: r[REQ_END] for r in reads}
        calls = run.rows("calls", t - span - 1e-9, t + 1e-9)
        # Calls that just started, at the cosmetic pace of the reads: copies first, so a few among
        # many first calls still show.
        moving = [c for c in calls if t - FLY <= c[CALL_START] <= t and not (c[CALL_END] > t and t - c[CALL_START] > SLOW)]
        shown = every([c for c in moving if c[CALL_COPY] > 0], FLIGHTS // 2)
        shown += every([c for c in moving if c[CALL_COPY] == 0], FLIGHTS - len(shown))
        for c in shown:
            flights.append((self.SERVICE, 1 + c[CALL_REPLICA], min(0.95, (t - c[CALL_START]) / FLY),
                            EXTRA2 if c[CALL_COPY] > 0 else WHITE))
        # Slow calls still running queue up along the edge by their replica: light orange while their
        # read waits for them, deep orange once it was answered by the other copy (wasted work).
        parked = [c for c in calls if c[CALL_END] > t and t - c[CALL_START] > SLOW]
        for c in every(parked, 2 * FLIGHTS):
            done = answered.get(c[1])
            colour = EXTRA3 if done is not None and done <= t else EXTRA1
            place = 0.55 + 0.4 * ((c[1] * 2654435761) % 97) / 96  # a spot of its own, steady frame to frame
            flights.append((self.SERVICE, 1 + c[CALL_REPLICA], place, colour))

        drops = [(-1, self.SERVICE, (t - r[REQ_END]) / BACK) for r in reads
                 if t - BACK <= r[REQ_END] <= t and r[REQ_OUTCOME] != OK]

        _, extra = w.load_at(run, t)
        sick = _slow_replicas(w.incident_at(variant, t))
        nodes = [_load_colour(extra), *(EXTRA2 if i in sick else BLUE for i in range(REPLICAS))]
        text, colour = _state(w, variant, t, extra)
        return ClusterFrame(nodes=nodes, flights=flights, drops=every(drops, 30),
                            state=(f"{text}   {w.s('topology', n=REPLICAS)}", colour))


@adapts("hedged_requests", "lanes")
class HedgedRequestsLanes(LaneAdapter):
    """Users wait for a read; a slow one turns light orange, and orange once a copy is sent (the
    orange dots flying to the door). The door is the hedge budget: shut while slow reads get no copy."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.hedged_requests import (
            REQ_END, REQ_HEDGED, REQ_ID, REQ_OUTCOME, REQ_START, SLOW,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        found = {}
        for r in run.active("requests", t, REQ_END):
            if t - r[REQ_START] < SLOW:
                colour = WHITE
            elif r[REQ_HEDGED] is not None and r[REQ_HEDGED] <= t:
                colour = EXTRA2
            else:
                colour = EXTRA1
            found[slot(r[REQ_ID], users)] = (colour, True)

        flying = run.rows("requests", t - FLY, t + 1e-9)
        flights = [(slot(r[REQ_ID], users), (t - r[REQ_START]) / FLY, WHITE, False)
                   for r in every(flying, FLIGHTS)]
        # Copies: from the same user, orange and bigger, as they are sent.
        span = run.max_dur.get("requests", 0.0)
        recent = run.rows("requests", t - FLY - span, t + 1e-9)
        hedges = [r for r in recent if r[REQ_HEDGED] is not None and t - FLY <= r[REQ_HEDGED] <= t]
        flights += [(slot(r[REQ_ID], users), (t - r[REQ_HEDGED]) / FLY, EXTRA2, True)
                    for r in every(hedges, FLIGHTS // 2)]
        ended = [r for r in run.rows("requests", t - BACK - span, t + 1e-9) if t - BACK <= r[REQ_END] <= t]
        outcomes = [(GREEN if r[REQ_OUTCOME] == OK else RED, (t - r[REQ_END]) / BACK)
                    for r in every(ended, OUTCOMES)]

        # The door: the budget. Shut while most slow reads get no copy, orange while some do not.
        refused = w.door_at(run, t)
        closed = refused is not None and refused >= 0.5
        door = None if refused is None or refused < 0.2 else RED if closed else EXTRA2

        load, extra = w.load_at(run, t)
        text, colour = _state(w, variant, t, extra)
        inc = w.incident_at(variant, t)
        return LaneFrame(users=found, flights=flights, outcomes=outcomes, closed=closed, door_color=door,
                         fill=min(1.0, load / 2), gauge=_load_colour(extra),
                         outline=EXTRA2 if inc is not None else OUTLINE, state=(text, colour))
