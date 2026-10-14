"""The lanes picture for lab n_plus_one_queries: pages are the users, the door is the connection pool,
the server is the database."""

from __future__ import annotations

from labs.n_plus_one_queries import lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, RED
from live.views.base import adapts
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


def _cost(queries: int) -> tuple[int, int, int]:
    """A page's colour: how many queries it needs (white 1-2, deeper orange for more)."""
    return EXTRA[0 if queries <= 2 else 1 if queries <= 10 else 2 if queries <= 30 else 3]


@adapts("n_plus_one_queries", "lanes")
class NPlusOneLanes(LaneAdapter):
    """Pages in flight, coloured by their query count; queries fly to the pool; the database fills up."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.n_plus_one_queries import (
            KIND_COLOUR, PAGE_END, PAGE_ID, PAGE_OK, PAGE_QUERIES, Q_KIND, Q_PAGE, Q_QUEUED,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(p[PAGE_ID], users): (_cost(p[PAGE_QUERIES]), True)
                 for p in run.active("pages", t, PAGE_END)}
        flying = run.rows("queries", t - FLY, t + 1e-9)
        flights = [(slot(q[Q_PAGE], users), (t - q[Q_QUEUED]) / FLY, KIND_COLOUR[q[Q_KIND]], False)
                   for q in every(flying, FLIGHTS)]
        span = run.max_dur.get("pages", 0.0)
        ended = [p for p in run.rows("pages", t - BACK - span, t + 1e-9) if t - BACK <= p[PAGE_END] <= t]
        outcomes = [(GREEN if p[PAGE_OK] else RED, (t - p[PAGE_END]) / BACK) for p in every(ended, OUTCOMES)]

        busy = w.busy_at(run, t)
        words = w.screen.STATES
        if busy >= lab.BUSY_MAX:
            state, colour = (words["overloaded"], RED), RED
        elif busy >= 0.6:
            state, colour = (words["busy"], EXTRA2), EXTRA2
        else:
            state, colour = (words["healthy"], GREEN), BLUE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            closed=busy >= lab.BUSY_MAX,  # every connection taken: queries wait at the pool
            door_color=EXTRA2 if 0.6 <= busy < lab.BUSY_MAX else None,
            fill=busy, gauge=colour, outline=colour if busy >= 0.6 else OUTLINE, state=state,
        )
