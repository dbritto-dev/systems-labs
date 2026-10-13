"""The lanes picture for lab retry_storm."""

from __future__ import annotations

from labs.retry_storm import lab as retry_lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, RED
from live.views.base import adapts
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
        flying = run.rows("calls", t - FLY, t + 1e-9)
        flights = [(slot(c[CALL_REQ], users), (t - c[CALL_START]) / FLY, EXTRA[min(3, c[CALL_ATTEMPT])],
                    c[CALL_ATTEMPT] > 0) for c in every(flying, FLIGHTS)]
        ended = [c for c in run.rows("calls", t - BACK - run.max_dur.get("calls", 0.0), t + 1e-9)
                 if t - BACK <= c[CALL_END] <= t]
        outcomes = [(GREEN if c[CALL_OK] else RED, (t - c[CALL_END]) / BACK) for c in every(ended, OUTCOMES)]

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
