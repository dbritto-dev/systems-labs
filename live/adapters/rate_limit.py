"""The pictures for lab rate_limit: lanes (the door is the rate limiter, the server is the backend)
and cluster (clients -> limiter -> backend)."""

from __future__ import annotations

from labs.rate_limit.scenario import FAILED, LIMITED, QUEUE, SERVED, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
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
        words = w.screen.STATES
        if overloaded:
            state, gauge, outline = (words["overloaded"], RED), RED, RED
        elif at_backend > WORKERS:
            state, gauge, outline = (words["busy"], EXTRA2), EXTRA2, EXTRA2
        else:
            state, gauge, outline = (words["healthy"], GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=rejecting,
            door_color=EXTRA3 if rejecting else None,
            fill=at_backend / (WORKERS + QUEUE), gauge=gauge, outline=outline, state=state,
        )


@adapts("rate_limit", "cluster")
class RateLimitCluster(ClusterAdapter):
    """The topology: clients -> the rate limiter (node 0) -> the backend (node 1). Normal requests fly
    white, a flooding client's orange; requests the limiter turns away die red before it, 503s from
    the backend die red between the two."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.rate_limit import REQ_END, REQ_FLOOD, REQ_OUTCOME, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = []
        for r in every(run.rows("requests", t - FLY, t + 1e-9), FLIGHTS):
            p = (t - r[REQ_START]) / FLY
            colour = EXTRA2 if r[REQ_FLOOD] else WHITE
            if p < 0.5:
                flights.append((-1, 0, p * 2, colour))
            elif r[REQ_OUTCOME] != LIMITED:  # let through
                flights.append((0, 1, (p - 0.5) * 2, colour))
        ended = [r for r in run.rows("requests", t - BACK - run.max_dur.get("requests", 0.0), t + 1e-9)
                 if t - BACK <= r[REQ_END] <= t and r[REQ_OUTCOME] in (LIMITED, FAILED)]
        drops = [((-1, 0) if r[REQ_OUTCOME] == LIMITED else (0, 1)) + ((t - r[REQ_END]) / BACK,)
                 for r in every(ended, OUTCOMES)]
        last = run.rows("requests", t - 1, t)
        limited = sum(1 for r in last if r[REQ_OUTCOME] == LIMITED)
        rejecting = bool(last) and limited / len(last) > 0.3
        at_backend = w.backend_at(run, t)
        words = w.screen.STATES
        if any(r[REQ_OUTCOME] == FAILED for r in last):
            backend, state = RED, (words["overloaded"], RED)
        elif at_backend > WORKERS:
            backend, state = EXTRA2, (words["busy"], EXTRA2)
        else:
            backend, state = BLUE, (words["healthy"], GREEN)
        return ClusterFrame(nodes=[EXTRA3 if rejecting else BLUE, backend], flights=flights, drops=drops,
                            state=(w.s("pic_state", state=state[0]), state[1]))
