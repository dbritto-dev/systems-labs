"""The pictures for lab n_plus_one_queries: lanes (pages are the users, the door is the connection pool,
the server is the database) and cluster (clients -> the app -> the database, every query a dot)."""

from __future__ import annotations

from labs.n_plus_one_queries import lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
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


QUERY_DOTS = 40  # queries drawn at once: enough for N+1 to look like the swarm it is


@adapts("n_plus_one_queries", "cluster")
class NPlusOneCluster(ClusterAdapter):
    """The topology: clients -> the app (node 0) -> the database (node 1), every round trip a dot.

    Page requests fly from the clients to the app (white). Every query of a sampled page flies from
    the app to the database, coloured by kind like in the lanes picture (white the list, orange one
    customer, light orange a batch, blue a join): N+1 is a swarm, a batch two dots, a join one.
    Queries waiting for a free connection sit just before the database. Pages users gave up on die
    red between the clients and the app. The database is orange when busy, red when every connection
    is taken; the line under it says how many queries a page needs.
    """

    APP, DB = 0, 1

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.n_plus_one_queries import (
            KIND_COLOUR, PAGE_END, PAGE_OK, PAGE_QUERIES, PAGE_START, Q_KIND, Q_QUEUED, Q_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = [(-1, self.APP, (t - p[PAGE_START]) / FLY, WHITE)
                   for p in every(run.rows("pages", t - FLY, t + 1e-9), FLIGHTS)]
        for q in every(run.rows("queries", t - FLY, t + 1e-9), QUERY_DOTS):
            p = (t - q[Q_QUEUED]) / FLY
            if q[Q_START] > t:  # no free connection yet: it waits before the database
                p = min(p, 0.85)
            flights.append((self.APP, self.DB, p, KIND_COLOUR[q[Q_KIND]]))
        span = run.max_dur.get("pages", 0.0)
        ended = [p for p in run.rows("pages", t - BACK - span, t + 1e-9) if t - BACK <= p[PAGE_END] <= t]
        drops = [(-1, self.APP, (t - p[PAGE_END]) / BACK) for p in every(ended, OUTCOMES) if not p[PAGE_OK]]

        recent = [p for p in run.rows("pages", t - 5 - span, t + 1e-9) if t - 5 <= p[PAGE_END] <= t]
        qpp = sum(p[PAGE_QUERIES] for p in recent) / len(recent) if recent else 0.0
        busy = w.busy_at(run, t)
        words = w.screen.STATES
        if busy >= lab.BUSY_MAX:
            db, state = RED, (words["overloaded"], RED)
        elif busy >= 0.6:
            db, state = EXTRA2, (words["busy"], EXTRA2)
        else:
            db, state = BLUE, (words["healthy"], GREEN)
        return ClusterFrame(nodes=[BLUE, db], flights=flights, drops=drops,
                            state=(w.s("pic_state", state=state[0], qpp=qpp), state[1]))
