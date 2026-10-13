"""The lanes picture for lab rate_limit: the door is the rate limiter, the server is the backend."""

from __future__ import annotations

from labs.rate_limit.scenario import FAILED, LIMITED, QUEUE, SERVED, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


@adapts("rate_limit", "lanes")
class RateLimitLanes(LaneAdapter):
    """Normal requests are white, a flooding client's orange; the door shuts on a flood it turns away."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.rate_limit import REQ_END, REQ_FLOOD, REQ_ID, REQ_OUTCOME, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(r[REQ_ID], users): (EXTRA2 if r[REQ_FLOOD] else WHITE, True)
                 for r in run.active("requests", t, REQ_END) if r[REQ_OUTCOME] != LIMITED}

        flying = run.rows("requests", t - FLY, t + 1e-9)
        flights = [(slot(r[REQ_ID], users), (t - r[REQ_START]) / FLY, EXTRA2 if r[REQ_FLOOD] else WHITE,
                    bool(r[REQ_FLOOD])) for r in every(flying, FLIGHTS)]
        ended = [r for r in run.rows("requests", t - BACK - run.max_dur.get("requests", 0.0), t + 1e-9)
                 if t - BACK <= r[REQ_END] <= t]
        colour = {SERVED: GREEN, LIMITED: EXTRA3, FAILED: RED}
        outcomes = [(colour[r[REQ_OUTCOME]], (t - r[REQ_END]) / BACK) for r in every(ended, OUTCOMES)]

        last = run.rows("requests", t - 1, t)
        limited = sum(1 for r in last if r[REQ_OUTCOME] == LIMITED)
        rejecting = bool(last) and limited / len(last) > 0.3  # turning a flood away
        at_backend = w.backend_at(run, t)
        overloaded = any(r[REQ_OUTCOME] == FAILED for r in last)
        if overloaded:
            state, gauge, outline = ("OVERLOADED", RED), RED, RED
        elif at_backend > WORKERS:
            state, gauge, outline = ("BUSY", EXTRA2), EXTRA2, EXTRA2
        else:
            state, gauge, outline = ("HEALTHY", GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=rejecting,
            door_color=EXTRA3 if rejecting else None,
            fill=at_backend / (WORKERS + QUEUE), gauge=gauge, outline=outline, state=state,
        )
