"""The pictures for lab conn_pool: lanes (the door is the pool, the server is the database) and
cluster (the topology: clients → pool → database)."""

from __future__ import annotations

from labs.conn_pool import lab as pool_lab
from labs.conn_pool.scenario import TOO_MANY
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


@adapts("conn_pool", "lanes")
class ConnPoolLanes(LaneAdapter):
    """Users wait for a connection (orange) or run their query (white); the door shuts while the
    database refuses connections; the gauge is the database's open connections out of 50."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.conn_pool import (
            REQ_END, REQ_FAIL, REQ_ID, REQ_NEW, REQ_OK, REQ_START, REQ_WAIT,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        found = {}
        for r in run.active("requests", t, REQ_END):
            if r[REQ_START] + r[REQ_WAIT] > t:  # still waiting: opening a connection, or queued for one
                colour = EXTRA2 if r[REQ_NEW] else EXTRA1
            else:
                colour = WHITE  # running its query
            found[slot(r[REQ_ID], users)] = (colour, True)

        flying = run.rows("requests", t - FLY, t + 1e-9)
        flights = [(slot(r[REQ_ID], users), (t - r[REQ_START]) / FLY,
                    EXTRA2 if r[REQ_NEW] else WHITE, bool(r[REQ_NEW])) for r in every(flying, FLIGHTS)]
        span = run.max_dur.get("requests", 0.0)
        ended = [r for r in run.rows("requests", t - BACK - span, t + 1e-9) if t - BACK <= r[REQ_END] <= t]
        outcomes = [(GREEN if r[REQ_OK] else RED, (t - r[REQ_END]) / BACK) for r in every(ended, OUTCOMES)]

        open_, busy = w.sample_at(run, t)
        refusing = any(r[REQ_FAIL] == TOO_MANY for r in ended)
        queued = len(w.waiting_at(run, t))
        words = w.screen.STATES
        if refusing or open_ >= pool_lab.MAX_CONNECTIONS:
            state, gauge, outline = (words["overloaded"], RED), RED, RED
        elif busy > pool_lab.CORES or queued > 20:
            state, gauge, outline = (words["busy"], EXTRA2), EXTRA2, EXTRA2
        else:
            state, gauge, outline = (words["healthy"], GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=refusing,
            door_color=EXTRA1 if queued > 20 else None,
            fill=open_ / pool_lab.GAUGE_MAX, gauge=gauge, outline=outline, state=state,
        )


@adapts("conn_pool", "cluster")
class ConnPoolCluster(ClusterAdapter):
    """The topology, live: clients → the pool (in the app) → the database.

    A request flies from the clients to the pool, then on to the database (orange while it opens a
    new connection). Requests waiting for a connection pile up at the pool. A pool that gives up
    (timeout) drops the request at the pool; a database that refuses drops it on the way there.
    """

    POOL, DB = 0, 1

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.conn_pool import REQ_END, REQ_FAIL, REQ_ID, REQ_NEW, REQ_OK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        waiting = {r[REQ_ID] for r in w.waiting_at(run, t)}
        flights = []
        for r in every(run.rows("requests", t - FLY, t + 1e-9), FLIGHTS):
            p = (t - r[REQ_START]) / FLY
            if r[REQ_ID] in waiting:  # still waiting for a connection: it stays at the pool
                flights.append((-1, self.POOL, min(0.95, 2 * p), EXTRA1))
            elif p < 0.5:
                flights.append((-1, self.POOL, 2 * p, WHITE))
            else:
                flights.append((self.POOL, self.DB, 2 * p - 1, EXTRA2 if r[REQ_NEW] else WHITE))
        span = run.max_dur.get("requests", 0.0)
        ended = [r for r in run.rows("requests", t - BACK - span, t + 1e-9)
                 if t - BACK <= r[REQ_END] <= t and not r[REQ_OK]]
        drops = [((self.POOL, self.DB) if r[REQ_FAIL] == TOO_MANY else (-1, self.POOL))
                 + ((t - r[REQ_END]) / BACK,) for r in every(ended, OUTCOMES)]

        open_, busy = w.sample_at(run, t)
        refusing = any(r[REQ_FAIL] == TOO_MANY for r in ended)
        queued = len(waiting)
        pool = BLUE if queued == 0 else EXTRA1 if queued <= 20 else EXTRA2
        if refusing or open_ >= pool_lab.MAX_CONNECTIONS:
            db, key, colour = RED, "overloaded", RED
        elif busy > pool_lab.CORES or queued > 20:
            db, key, colour = (EXTRA2 if busy > pool_lab.CORES else BLUE), "busy", EXTRA2
        else:
            db, key, colour = BLUE, "healthy", GREEN
        state = f"{w.screen.STATES[key]}   {w.s('topology')}"
        return ClusterFrame(nodes=[pool, db], flights=flights, drops=drops, state=(state, colour))
