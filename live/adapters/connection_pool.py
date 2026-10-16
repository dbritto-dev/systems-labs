"""The pictures for lab connection_pool: lanes (the door is the pool, the server is the database) and
cluster (the topology: clients → pool → database) and relay (users → the pool, its connections in use →
the database)."""

from __future__ import annotations

from labs.connection_pool import lab as pool_lab
from labs.connection_pool.scenario import TIMED_OUT, TOO_MANY
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every, just_ended, just_sent, user_flights, user_outcomes
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame


@adapts("connection_pool", "lanes")
class ConnPoolLanes(LaneAdapter):
    """Users wait for a connection (orange) or run their query (white); the door shuts while the
    database refuses connections; the gauge is the database's open connections out of 50."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.connection_pool import (
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

        flying = just_sent(run, "requests", t)
        flights = user_flights(every(flying, FLIGHTS), t, REQ_START,
                               lambda r: (slot(r[REQ_ID], users), EXTRA2 if r[REQ_NEW] else WHITE, bool(r[REQ_NEW])))
        ended = just_ended(run, "requests", REQ_END, t)
        outcomes = user_outcomes(ended, t, REQ_END, lambda r: GREEN if r[REQ_OK] else RED)

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


@adapts("connection_pool", "cluster")
class ConnPoolCluster(ClusterAdapter):
    """The topology, live: clients → the pool (in the app) → the database.

    A request flies from the clients to the pool, then on to the database (orange while it opens a
    new connection). Requests waiting for a connection pile up at the pool. A pool that gives up
    (timeout) drops the request at the pool; a database that refuses drops it on the way there.
    """

    POOL, DB = 0, 1

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.connection_pool import REQ_END, REQ_FAIL, REQ_ID, REQ_NEW, REQ_OK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        waiting = {r[REQ_ID] for r in w.waiting_at(run, t)}
        flights = []
        for r in every(just_sent(run, "requests", t), FLIGHTS):
            p = (t - r[REQ_START]) / FLY
            if r[REQ_ID] in waiting:  # still waiting for a connection: it stays at the pool
                flights.append((-1, self.POOL, min(0.95, 2 * p), EXTRA1))
            elif p < 0.5:
                flights.append((-1, self.POOL, 2 * p, WHITE))
            else:
                flights.append((self.POOL, self.DB, 2 * p - 1, EXTRA2 if r[REQ_NEW] else WHITE))
        ended = [r for r in just_ended(run, "requests", REQ_END, t) if not r[REQ_OK]]
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


@adapts("connection_pool", "relay")
class ConnPoolRelay(RelayAdapter):
    """Users → the door → the app's connection pool (the relay) → the database (the server on the right).

    The pool's gauge is its connections in use (lent to a request running its query), against the
    database's limit of 50; the word under it is that count. Its outline is light orange while requests
    wait for a connection, orange when over 20 wait, red while acquire() gives up (a pool timeout); users
    waiting for a connection are orange (light: queued; deeper: opening a new one). Requests fly from the
    pool to the database once they have a connection: white on a reused one, orange and bigger when it
    opens a new one; a request the database refuses (too many connections) flies red. A request whose
    acquire() timed out never leaves the pool: red, at its edge. The database is as in lanes: its gauge
    is the connections open on it, red while it refuses them."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.connection_pool import REQ_END, REQ_FAIL, REQ_NEW, REQ_START, REQ_WAIT

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = ConnPoolLanes(w).frame(variant, t, users)  # the users, the database and its state
        half = FLY / 2
        flights = [(i, min(1.0, 2 * k), col, big) for i, k, col, big in lane.flights if k < 0.5]
        span = run.max_dur.get("requests", 0.0)
        recent = run.rows("requests", t - span - FLY - 1e-9, t + 1e-9)
        hops, stuck = [], []
        for r in recent:
            if r[REQ_FAIL] == TIMED_OUT:  # gave up at the pool: it never reaches the database
                if t - BACK <= r[REQ_END] <= t:
                    stuck.append(r)
                continue
            got = max(r[REQ_START] + half, r[REQ_START] + r[REQ_WAIT])  # through the door, with a connection
            if got <= t <= got + half:
                refused = r[REQ_FAIL] == TOO_MANY
                hops.append(((t - got) / half, RED if refused else EXTRA2 if r[REQ_NEW] else WHITE,
                             bool(r[REQ_NEW]) or refused))
        red = [h for h in hops if h[1] == RED]
        hops = every(red, FLIGHTS // 2) + every([h for h in hops if h[1] != RED], FLIGHTS - min(len(red), FLIGHTS // 2))
        hops += [(0.04 * j, RED, False) for j in range(min(3, len(stuck) // 2 + bool(stuck)))]

        in_use = sum(1 for r in run.active("requests", t, REQ_END)
                     if r[REQ_START] + r[REQ_WAIT] <= t and r[REQ_FAIL] == 0)
        queued = len(w.waiting_at(run, t))
        if stuck:
            colour = RED
        elif queued > 20:
            colour = EXTRA2
        elif queued:
            colour = EXTRA1
        else:
            colour = OUTLINE
        relay = Relay(label=(w.s("relay_in_use", n=in_use), WHITE if colour == OUTLINE else colour),
                      fill=in_use / pool_lab.MAX_CONNECTIONS, gauge=BLUE if colour == OUTLINE else colour,
                      outline=colour)
        return RelayFrame(users=lane.users, flights=flights, outcomes=lane.outcomes, fill=lane.fill,
                          gauge=lane.gauge, outline=lane.outline, state=lane.state, relay=relay, hops=hops)
