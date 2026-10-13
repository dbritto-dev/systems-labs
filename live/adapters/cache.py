"""The lanes picture for lab cache."""

from __future__ import annotations

from labs.cache import lab as cache_lab
from labs.cache.scenario import HIT
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, GREEN, RED
from live.views.base import adapts
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


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
                    r[READ_KIND] != HIT) for r in every(flying, FLIGHTS)]
        ended = [r for r in run.rows("reads", t - BACK - run.max_dur.get("reads", 0.0), t + 1e-9)
                 if t - BACK <= r[READ_END] <= t]
        outcomes = [(GREEN if r[READ_OK] else RED, (t - r[READ_END]) / BACK) for r in every(ended, OUTCOMES)]

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
