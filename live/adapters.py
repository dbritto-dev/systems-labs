"""Adapters: each turns one lab's World into the model of one view (views/). A lab is drawn with
`World.view`; the adapter registered for (lab, view) here is what feeds it. To show a new lab in lanes,
add a LaneAdapter subclass with `@adapts("<lab id>", "lanes")`.
"""

from __future__ import annotations

from labs.cache import lab as cache_lab
from labs.cache.scenario import HIT
from labs.retry_storm import lab as retry_lab
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, RED
from live.views.base import adapts
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

FLY = 0.35  # seconds a dot takes to reach the door (cosmetic: real calls take ~10 ms)
BACK = 0.4  # seconds an outcome stays at the door
FLIGHTS, OUTCOMES = 14, 8


def _every(rows: list, most: int) -> list:
    """At most `most` rows, evenly spread."""
    return rows[:: max(1, len(rows) // most)][:most]


@adapts("retry_storm", "lanes")
class RetryStormLanes(LaneAdapter):
    """Users send ~100 requests/s; each call is coloured by its try; the door closes while the service is down."""

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
                    c[CALL_ATTEMPT] > 0) for c in _every(flying, FLIGHTS)]
        ended = [c for c in run.rows("calls", t - BACK - run.max_dur.get("calls", 0.0), t + 1e-9)
                 if t - BACK <= c[CALL_END] <= t]
        outcomes = [(GREEN if c[CALL_OK] else RED, (t - c[CALL_END]) / BACK) for c in _every(ended, OUTCOMES)]

        load = w.load_at(run, t)
        ask = run.count("requests", t - 1, t) or w.rate
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=down,
            door_color=EXTRA2 if degraded else None,
            fill=load / retry_lab.GAUGE_MAX,
            gauge=EXTRA2 if load / ask > retry_lab.GAUGE_ORANGE else BLUE,
            outline=RED if down else EXTRA2 if degraded else OUTLINE,
            state=("DOWN", RED) if down else ("DEGRADED", EXTRA2) if degraded else ("HEALTHY", GREEN),
        )


@adapts("cache", "lanes")
class CacheLanes(LaneAdapter):
    """The door is the cache: hits come back from the door, misses wait on the database behind it."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.cache import (
            KIND_COLOUR, PAGE_END, PAGE_ID, PAGE_KIND, READ_END, READ_KIND, READ_OK, READ_PAGE, READ_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(p[PAGE_ID], users): (KIND_COLOUR[p[PAGE_KIND]], True)
                 for p in run.active("pages", t, PAGE_END)}

        flying = run.rows("reads", t - FLY, t + 1e-9)
        flights = [(slot(r[READ_PAGE], users), (t - r[READ_START]) / FLY, KIND_COLOUR[r[READ_KIND]],
                    r[READ_KIND] != HIT) for r in _every(flying, FLIGHTS)]
        ended = [r for r in run.rows("reads", t - BACK - run.max_dur.get("reads", 0.0), t + 1e-9)
                 if t - BACK <= r[READ_END] <= t]
        outcomes = [(GREEN if r[READ_OK] else RED, (t - r[READ_END]) / BACK) for r in _every(ended, OUTCOMES)]

        inflight, queued = w.db_state(run, t)
        rejected = any(not d[5] for d in run.rows("db", t - 1, t))
        if queued >= 40 or rejected:
            state, gauge, outline = ("OVERLOADED", RED), RED, RED
        elif queued > 0:
            state, gauge, outline = ("BUSY", EXTRA2), EXTRA2, EXTRA2
        else:
            state, gauge, outline = ("HEALTHY", GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=EXTRA2 if w.flushed_recently(variant, t) else None,  # the cache is empty
            fill=(inflight + queued) / cache_lab.GAUGE_MAX, gauge=gauge, outline=outline, state=state,
        )
