"""The pictures for lab database_index: lanes (users, the database as the server) and cluster (clients ->
the database's queue -> its 4 workers, each coloured by the query it is running)."""

from __future__ import annotations

from labs.database_index import lab as db_lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, DIM, EXTRA, EXTRA1, EXTRA2, GREEN, RED
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


def state(world, overloaded: bool, busy: bool) -> tuple[str, tuple[int, int, int]]:
    """The words under the server, in the language in use."""
    words = world.screen.STATES
    if overloaded:
        return words["overloaded"], RED
    return (words["busy"], EXTRA2) if busy else (words["healthy"], GREEN)


@adapts("database_index", "lanes")
class DbIndexLanes(LaneAdapter):
    """Logins and range queries, coloured by how many rows they read; the door closes while users give up."""

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
            state=state(w, overloaded, busy),
        )


@adapts("database_index", "cluster")
class DbIndexCluster(ClusterAdapter):
    """The topology: clients -> the database's queue (node 0) -> its 4 workers (nodes 1-4).

    A query flies from the clients to the queue, then on to a worker, coloured by how many rows it
    reads (white a few, deeper orange for more, deepest a full scan). Queries waiting for a worker sit
    at the queue. Each worker is coloured by the query it runs right now (dim while idle): a full scan
    keeps a worker deep orange for a long time, an index lookup is gone in a blink. Users who gave up
    waiting die red before the queue. The line under the grid says how many rows a login reads, on average.
    """

    QUEUE = 0

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.database_index import Q_END, Q_ID, Q_KIND, Q_RAN, Q_READ, Q_START
        from labs.database_index.scenario import LOOKUP

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()

        def colour(q: tuple) -> tuple[int, int, int]:
            return EXTRA[db_lab.bucket(q[Q_READ])] if q[Q_RAN] else RED

        def began(q: tuple) -> float:  # when it got a worker: it then ran for its rows' worth of time
            return q[Q_END] - (db_lab.OVERHEAD + q[Q_READ] * db_lab.ROW_COST) if q[Q_RAN] else q[Q_END]

        active = run.active("queries", t, Q_END)
        running = sorted((q for q in active if q[Q_RAN] and began(q) <= t), key=began)[:db_lab.WORKERS]
        waiting = [q for q in active if began(q) > t]
        workers = [colour(q) for q in running] + [DIM] * (db_lab.WORKERS - len(running))
        at = {q[Q_ID]: 1 + k for k, q in enumerate(running)}

        flights = []
        for q in every(run.rows("queries", t - FLY, t + 1e-9), FLIGHTS):
            p = (t - q[Q_START]) / FLY
            if p < 0.5 or began(q) > t:  # into the queue, where it waits for a worker
                flights.append((-1, self.QUEUE, min(2 * p, 0.95 if p >= 0.5 else 1.0), colour(q)))
            else:  # on to a worker (the one running it, if it still is)
                worker = at.get(q[Q_ID], 1 + q[Q_ID] % db_lab.WORKERS)
                flights.append((self.QUEUE, worker, 2 * p - 1, colour(q)))
        span = run.max_dur.get("queries", 0.0)
        gave_up = [q for q in run.rows("queries", t - BACK - span, t + 1e-9)
                   if t - BACK <= q[Q_END] <= t and not q[Q_RAN]]
        drops = [(-1, self.QUEUE, (t - q[Q_END]) / BACK) for q in every(gave_up, OUTCOMES)]

        logins = [q for q in run.rows("queries", t - 5, t + 1e-9) if q[Q_KIND] == LOOKUP and q[Q_RAN]]
        read = sum(q[Q_READ] for q in logins) / len(logins) if logins else 0.0
        overloaded = w.timeouts_at(run, t) > 0
        busy = len(active) > db_lab.WORKERS * 2
        queue = RED if overloaded else EXTRA2 if busy else EXTRA1 if waiting else BLUE
        word, tone = state(w, overloaded, busy)
        return ClusterFrame(nodes=[queue, *workers], flights=flights, drops=drops,
                            state=(w.s("pic_state", state=word, read=read), tone))
