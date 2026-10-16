"""The pictures for lab caching: lanes (the door is the cache), cluster (app, cache, database) and relay
(users -> the cache as a server of its own -> the database, every database read a dot)."""

from __future__ import annotations

from labs.caching import lab as cache_lab
from labs.caching.scenario import HIT
from live.adapters.common import (
    BACK, FLIGHTS, FLY, OUTCOMES, every, just_ended, just_sent, rare_rows_first, user_flights, user_outcomes,
)
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, RED
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame

LOAD_DOTS = 24  # database reads drawn at once, at most
LOAD_SAMPLE = 4  # ... one in this many


@adapts("caching", "lanes")
class CacheLanes(LaneAdapter):
    """The door is the cache: hits come back from the door, misses wait on the database behind it."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.caching import (
            KIND_COLOUR, PAGE_END, PAGE_ID, PAGE_KIND, READ_END, READ_KIND, READ_OK, READ_PAGE, READ_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(p[PAGE_ID], users): (KIND_COLOUR[p[PAGE_KIND]], True)
                 for p in run.active("pages", t, PAGE_END)}

        flying = just_sent(run, "reads", t)
        flights = user_flights(every(flying, FLIGHTS), t, READ_START,
                               lambda r: (slot(r[READ_PAGE], users), KIND_COLOUR[r[READ_KIND]], r[READ_KIND] != HIT))
        ended = just_ended(run, "reads", READ_END, t)
        outcomes = user_outcomes(ended, t, READ_END, lambda r: GREEN if r[READ_OK] else RED)

        inflight, queued = w.db_state(run, t)
        rejected = any(not d[5] for d in run.rows("db", t - 1, t))
        words = w.screen.STATES
        if queued >= 40 or rejected:
            state, gauge, outline = (words["overloaded"], RED), RED, RED
        elif queued > 0:
            state, gauge, outline = (words["busy"], EXTRA2), EXTRA2, EXTRA2
        else:
            state, gauge, outline = (words["healthy"], GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=EXTRA2 if w.flushed_recently(variant, t) else None,  # the cache is empty
            fill=(inflight + queued) / cache_lab.GAUGE_MAX, gauge=gauge, outline=outline, state=state,
        )


@adapts("caching", "cluster")
class CacheCluster(ClusterAdapter):
    """The topology: clients -> the app (node 0), which asks the cache (node 1, right) and, on a miss,
    reads the database itself (node 2, below). Dots are coloured like the reads in the lanes picture
    (white hit, orange first load, deeper orange duplicate load); rejected reads die red on the way to
    the database. The cache turns orange while it is empty after a flush."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.caching import KIND_COLOUR, READ_END, READ_KIND, READ_OK, READ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = []
        for r in every(just_sent(run, "reads", t), FLIGHTS):
            p = (t - r[READ_START]) / FLY
            colour = KIND_COLOUR[r[READ_KIND]]
            if p < 0.5:  # into the app
                flights.append((-1, 0, p * 2, colour))
            else:  # then to the cache (a hit) or the database (a miss)
                flights.append((0, 1 if r[READ_KIND] == HIT else 2, (p - 0.5) * 2, colour))
        ended = [r for r in just_ended(run, "reads", READ_END, t) if not r[READ_OK]]
        drops = [(0, 2, (t - r[READ_END]) / BACK) for r in every(ended, OUTCOMES)]
        inflight, queued = w.db_state(run, t)
        rejected = any(not d[5] for d in run.rows("db", t - 1, t))
        words = w.screen.STATES
        if queued >= 40 or rejected:
            db, state = RED, (words["overloaded"], RED)
        elif queued > 0:
            db, state = EXTRA2, (words["busy"], EXTRA2)
        else:
            db, state = BLUE, (words["healthy"], GREEN)
        empty = w.flushed_recently(variant, t)
        key = "pic_empty" if empty else "pic_state"
        return ClusterFrame(nodes=[BLUE, EXTRA2 if empty else BLUE, db], flights=flights, drops=drops,
                            state=(w.s(key, state=state[0]), state[1]))


@adapts("caching", "relay")
class CacheRelay(RelayAdapter):
    """The lanes picture with the cache as a server of its own: users -> the door -> the cache -> the
    database. Reads fly from the users to the door, coloured like in the lanes picture. The cache's
    gauge is its hit ratio over the last half second (blue at 80% or more, orange below, red near none);
    its outline turns orange for the seconds after a flush emptied it. Every database read (a miss, one
    in LOAD_SAMPLE drawn) flies from the cache to the database: orange a first load, deep orange and big
    a duplicate load of a key that is already loading, red a read the full queue rejected; reads waiting
    in the queue line up by the database. After a flush without single-flight that line is a swarm of
    duplicates; with it, one dot per key. The database is the server on the right, as in the lanes
    picture."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.caching import DB_DUP, DB_END, DB_KEY, DB_OK, DB_PAGE, DB_QUEUED, DB_START, READ_KIND

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = CacheLanes(w).frame(variant, t, users)

        def colour(d):
            return RED if not d[DB_OK] else EXTRA3 if d[DB_DUP] else EXTRA2

        # One database read in LOAD_SAMPLE is drawn (the same ones from frame to frame), so the line is as
        # busy as the database: a few dots in calm times, a swarm in a stampede.
        loads = [d for d in just_sent(run, "db", t)
                 if slot(d[DB_PAGE] * 7919 + d[DB_KEY], LOAD_SAMPLE) == 0]
        shown = rare_rows_first(loads, lambda d: d[DB_DUP] or not d[DB_OK], LOAD_DOTS, LOAD_DOTS // 2)
        hops = []
        for d in shown:
            k = (t - d[DB_QUEUED]) / FLY
            if d[DB_OK] and (d[DB_START] is None or d[DB_START] > t):
                k = min(k, 0.85)  # still in the queue: it waits before the database
            hops.append((k, colour(d), bool(d[DB_DUP])))
        queued = [d for d in run.active("db", t, DB_END) if d[DB_QUEUED] < t - FLY
                  and (d[DB_START] is None or d[DB_START] > t)]
        hops += [(0.85 - 0.05 * j, colour(d), bool(d[DB_DUP]))  # the queue, the oldest at the database
                 for j, d in enumerate(every(queued, 8))]

        reads = run.rows("reads", t - 0.5, t + 1e-9)
        hits = sum(r[READ_KIND] == HIT for r in reads) / len(reads) if reads else 0.0
        gauge = BLUE if hits >= cache_lab.HIT_MIN else EXTRA2 if hits >= 0.05 else RED
        if w.flushed_recently(variant, t):
            label, outline = (w.s("relay_flushed", hits=hits), EXTRA2), EXTRA2
        else:
            label, outline = (w.s("relay_cache", hits=hits), gauge if gauge != BLUE else OUTLINE), OUTLINE
        return RelayFrame(
            users=lane.users, flights=lane.flights, outcomes=lane.outcomes,
            fill=lane.fill, gauge=lane.gauge, outline=lane.outline, state=lane.state,
            relay=Relay(label=label, fill=hits, gauge=gauge, outline=outline), hops=hops,
        )
