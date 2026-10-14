"""The lanes picture for lab database_index."""

from __future__ import annotations

from labs.database_index import lab as db_lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, RED
from live.views.base import adapts
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


@adapts("database_index", "lanes")
class DbIndexLanes(LaneAdapter):
    """Logins and range queries, coloured by how many rows they read; the door closes while users give up."""

    def state(self, overloaded: bool, busy: bool) -> tuple[str, tuple[int, int, int]]:
        """The words under the server, in the language in use."""
        words = self.world.screen.STATES
        if overloaded:
            return words["overloaded"], RED
        return (words["busy"], EXTRA2) if busy else (words["healthy"], GREEN)

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.database_index import Q_END, Q_ID, Q_OK, Q_RAN, Q_READ, Q_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(q: tuple) -> tuple[int, int, int]:
            return EXTRA[db_lab.bucket(q[Q_READ])] if q[Q_RAN] else RED

        # Users waiting for an answer, coloured by how much their query reads.
        waiting = run.active("queries", t, Q_END)
        found = {slot(q[Q_ID], users): (colour(q), True) for q in waiting}

        # Queries on their way to the database, and what came back.
        flying = run.rows("queries", t - FLY, t + 1e-9)
        flights = [(slot(q[Q_ID], users), (t - q[Q_START]) / FLY, colour(q),
                    q[Q_READ] > db_lab.BUCKETS[-1]) for q in every(flying, FLIGHTS)]
        span = run.max_dur.get("queries", 0.0)
        ended = [q for q in run.rows("queries", t - BACK - span, t + 1e-9) if t - BACK <= q[Q_END] <= t]
        outcomes = [(GREEN if q[Q_OK] else RED, (t - q[Q_END]) / BACK) for q in every(ended, OUTCOMES)]

        overloaded = w.timeouts_at(run, t) > 0
        busy = len(waiting) > db_lab.WORKERS * 2
        fill = len(waiting) / db_lab.QUEUE_MAX
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=overloaded,
            fill=fill,
            gauge=EXTRA2 if fill > 0.5 else BLUE,
            outline=RED if overloaded else EXTRA2 if busy else OUTLINE,
            state=self.state(overloaded, busy),
        )
