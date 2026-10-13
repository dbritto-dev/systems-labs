"""The lanes picture for lab circuit_breaker: the door is the breaker in front of the slow dependency."""

from __future__ import annotations

from labs.circuit_breaker.scenario import DEPS, OK, REFUSED
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
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
        if full:
            state, gauge, outline = ("OVERLOADED", RED), RED, RED
        elif inc is not None:
            state, gauge, outline = ("DEGRADED", EXTRA2), EXTRA2 if busy >= w.workers * 0.8 else BLUE, EXTRA2
        else:
            state, gauge, outline = ("HEALTHY", GREEN), BLUE, OUTLINE
        return LaneFrame(users=found, flights=flights, outcomes=outcomes, closed=closed, door_color=door,
                         fill=busy / w.workers, gauge=gauge, outline=outline, state=state)
