"""The pictures for lab circuit_breaker: lanes (the door is the breaker in front of the slow
dependency) and cluster (the topology: clients → service → payments and recommendations)."""

from __future__ import annotations

from labs.circuit_breaker.scenario import DEPS, OK, REFUSED
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

SLOW_CALL = 0.1  # a call running longer than this colours its user "slow call"


@adapts("circuit_breaker", "lanes")
class CircuitBreakerLanes(LaneAdapter):
    """Users wait for a worker, then for a dependency; the door shuts while calls are refused at once."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.circuit_breaker import (
            REQ_DEP, REQ_END, REQ_GOT, REQ_ID, REQ_OUTCOME, REQ_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        # Users still waiting: for a worker, on a slow call, or on a fast one.
        found = {}
        for r in run.active("requests", t, REQ_END):
            got = r[REQ_GOT]
            if got is None or got > t:
                colour = EXTRA1
            elif t - got > SLOW_CALL:
                colour = EXTRA2
            else:
                colour = WHITE
            found[slot(r[REQ_ID], users)] = (colour, True)

        flying = run.rows("requests", t - FLY, t + 1e-9)
        flights = [(slot(r[REQ_ID], users), (t - r[REQ_START]) / FLY, WHITE, False)
                   for r in every(flying, FLIGHTS)]
        span = run.max_dur.get("requests", 0.0)
        ended = [r for r in run.rows("requests", t - BACK - span, t + 1e-9) if t - BACK <= r[REQ_END] <= t]
        outcomes = [(GREEN if r[REQ_OUTCOME] == OK else EXTRA3 if r[REQ_OUTCOME] == REFUSED else RED,
                     (t - r[REQ_END]) / BACK) for r in every(ended, OUTCOMES)]

        # The door: shut while calls to a dependency are refused at once (an open breaker),
        # orange while some are (a full bulkhead, or a half-open breaker letting a probe through).
        refused = max(w.door_at(run, t, d) for d in range(len(DEPS)))
        closed = refused >= 0.8
        door = None if refused < 0.3 else EXTRA2 if not closed else RED

        busy = w.busy_at(run, t)
        full = busy >= w.workers
        inc = w.incident_at(variant, t)
        words = w.screen.STATES
        if full:
            state, gauge, outline = (words["overloaded"], RED), RED, RED
        elif inc is not None:
            state, gauge, outline = (words["degraded"], EXTRA2), EXTRA2 if busy >= w.workers * 0.8 else BLUE, EXTRA2
        else:
            state, gauge, outline = (words["healthy"], GREEN), BLUE, OUTLINE
        return LaneFrame(users=found, flights=flights, outcomes=outcomes, closed=closed, door_color=door,
                         fill=busy / w.workers, gauge=gauge, outline=outline, state=state)


@adapts("circuit_breaker", "cluster")
class CircuitBreakerCluster(ClusterAdapter):
    """The topology, live: clients → the service (its workers) → payments and recommendations.

    Requests fly from the clients to the service; calls fly from the service to a dependency, and a
    slow call stays near the dependency, orange, holding its worker. Calls refused without calling
    (an open breaker, a full bulkhead) and calls that fail die in red on the edge to that dependency;
    users who give up die on the way in.
    """

    SERVICE = 0

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.circuit_breaker import (
            CALL_DEP, CALL_END, CALL_OUTCOME, CALL_START, REQ_DEP, REQ_END, REQ_OUTCOME, REQ_START,
        )
        from labs.circuit_breaker.scenario import CALL_OK, GAVE_UP

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = [(-1, self.SERVICE, (t - r[REQ_START]) / FLY, WHITE)
                   for r in every(run.rows("requests", t - FLY, t + 1e-9), FLIGHTS // 2)]
        span = run.max_dur.get("calls", 0.0)
        # Calls that just started (at the same cosmetic pace as the requests), and slow calls still
        # running, parked by their dependency while they hold a worker.
        calls = [c for c in run.rows("calls", t - span - 1e-9, t + 1e-9)
                 if c[CALL_START] >= t - FLY or c[CALL_END] > t]
        for c in every(calls, FLIGHTS):
            age = t - c[CALL_START]
            slow = c[CALL_END] > t and age > SLOW_CALL
            flights.append((self.SERVICE, 1 + c[CALL_DEP], min(0.95, age / FLY), EXTRA2 if slow else WHITE))

        drops = []
        rspan = run.max_dur.get("requests", 0.0)
        for r in run.rows("requests", t - BACK - rspan, t + 1e-9):
            if not t - BACK <= r[REQ_END] <= t:
                continue
            if r[REQ_OUTCOME] == REFUSED:
                drops.append((self.SERVICE, 1 + r[REQ_DEP], (t - r[REQ_END]) / BACK))
            elif r[REQ_OUTCOME] == GAVE_UP:
                drops.append((-1, self.SERVICE, (t - r[REQ_END]) / BACK))
        for c in run.rows("calls", t - BACK - span, t + 1e-9):
            if t - BACK <= c[CALL_END] <= t and c[CALL_OUTCOME] != CALL_OK:
                drops.append((self.SERVICE, 1 + c[CALL_DEP], (t - c[CALL_END]) / BACK))

        busy = w.busy_at(run, t)
        inc = w.incident_at(variant, t)
        service = RED if busy >= w.workers else EXTRA2 if busy >= w.workers * 0.8 else BLUE
        deps = []
        for i, name in enumerate(DEPS):
            if w.door_at(run, t, i) >= 0.8:
                deps.append(RED)  # refused at once: the breaker is open
            elif inc is not None and inc.kind == name:
                deps.append(EXTRA2)  # slow
            else:
                deps.append(BLUE)
        words = w.screen.STATES
        if busy >= w.workers:
            key, colour = "overloaded", RED
        elif inc is not None:
            key, colour = "degraded", EXTRA2
        else:
            key, colour = "healthy", GREEN
        topology = w.s("topology", a=w.dep_name(DEPS[0]), b=w.dep_name(DEPS[1]))
        return ClusterFrame(nodes=[service, *deps], flights=flights, drops=every(drops, 30),
                            state=(f"{words[key]}   {topology}", colour))
