"""The pictures for lab retry_storm: lanes (users, a door, the service) and cluster (the topology)."""

from __future__ import annotations

from labs.retry_storm import lab as retry_lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every, just_ended, just_sent, user_flights, user_outcomes
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


@adapts("retry_storm", "lanes")
class RetryStormLanes(LaneAdapter):
    """Users send ~100 requests/s; each call is coloured by its try; the door closes while the service is down."""

    def state(self, down: bool, degraded: bool) -> tuple[str, tuple[int, int, int]]:
        """The words under the server, in the language in use."""
        words = self.world.screen.STATES
        if down:
            return words["down"], RED
        return (words["degraded"], EXTRA2) if degraded else (words["healthy"], GREEN)

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.retry_storm import (
            CALL_ATTEMPT, CALL_END, CALL_OK, CALL_REQ, CALL_START, REQ_END, REQ_ID,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        inc = w.incident_at(variant, t)
        down = inc is not None and inc.kind == "outage"
        degraded = inc is not None and not down

        # Users still waiting, coloured by which try they are on.
        span = run.max_dur.get("requests", 0.0) + 0.1
        tries: dict[int, int] = {}
        for c in run.rows("calls", t - span, t + 1e-9):
            tries[c[CALL_REQ]] = max(tries.get(c[CALL_REQ], 0), c[CALL_ATTEMPT])
        found = {slot(r[REQ_ID], users): (EXTRA[min(3, tries.get(r[REQ_ID], 0))], True)
                 for r in run.active("requests", t, REQ_END)}

        # Calls in flight to the door, and what happened there.
        flying = just_sent(run, "calls", t)
        flights = user_flights(every(flying, FLIGHTS), t, CALL_START, lambda c: (
            slot(c[CALL_REQ], users), EXTRA[min(3, c[CALL_ATTEMPT])], c[CALL_ATTEMPT] > 0))
        ended = just_ended(run, "calls", CALL_END, t)
        outcomes = user_outcomes(ended, t, CALL_END, lambda c: GREEN if c[CALL_OK] else RED)

        load = w.load_at(run, t)
        ask = run.count("requests", t - 1, t) or w.rate
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=down,
            door_color=EXTRA2 if degraded else None,
            fill=load / retry_lab.GAUGE_MAX,
            gauge=EXTRA2 if load / ask > retry_lab.GAUGE_ORANGE else BLUE,
            outline=RED if down else EXTRA2 if degraded else OUTLINE,
            state=self.state(down, degraded),
        )


@adapts("retry_storm", "cluster")
class RetryStormCluster(ClusterAdapter):
    """The topology: clients -> your Client (node 0) -> the service (node 1). Requests fly in white;
    calls to the service are coloured by their try; failed calls die red between the two."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.retry_storm import CALL_ATTEMPT, CALL_END, CALL_OK, CALL_START, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        inc = w.incident_at(variant, t)
        down = inc is not None and inc.kind == "outage"
        degraded = inc is not None and not down
        flights = [(-1, 0, (t - r[REQ_START]) / FLY, WHITE) for r in every(just_sent(run, "requests", t), 8)]
        flights += [(0, 1, (t - c[CALL_START]) / FLY, EXTRA[min(3, c[CALL_ATTEMPT])])
                    for c in every(just_sent(run, "calls", t), FLIGHTS)]
        ended = [c for c in just_ended(run, "calls", CALL_END, t) if not c[CALL_OK]]
        drops = [(0, 1, (t - c[CALL_END]) / BACK) for c in every(ended, OUTCOMES)]
        load = w.load_at(run, t)
        ask = run.count("requests", t - 1, t) or w.rate
        service = RED if down else EXTRA2 if degraded or load / ask > retry_lab.GAUGE_ORANGE else BLUE
        word, colour = RetryStormLanes.state(self, down, degraded)  # type: ignore[arg-type]
        return ClusterFrame(nodes=[BLUE, service], flights=flights, drops=drops,
                            state=(w.s("pic_state", state=word), colour))
