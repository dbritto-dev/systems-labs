"""The pictures for lab cache: lanes (the door is the cache) and cluster (app, cache, database)."""

from __future__ import annotations

from labs.cache import lab as cache_lab
from labs.cache.scenario import HIT
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, GREEN, RED
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
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


@adapts("cache", "cluster")
class CacheCluster(ClusterAdapter):
    """The topology: clients -> the app (node 0), which asks the cache (node 1, right) and, on a miss,
    reads the database itself (node 2, below). Dots are coloured like the reads in the lanes picture
    (white hit, orange first load, deeper orange duplicate load); rejected reads die red on the way to
    the database. The cache turns orange while it is empty after a flush."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.cache import KIND_COLOUR, READ_END, READ_KIND, READ_OK, READ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = []
        for r in every(run.rows("reads", t - FLY, t + 1e-9), FLIGHTS):
            p = (t - r[READ_START]) / FLY
            colour = KIND_COLOUR[r[READ_KIND]]
            if p < 0.5:  # into the app
                flights.append((-1, 0, p * 2, colour))
            else:  # then to the cache (a hit) or the database (a miss)
                flights.append((0, 1 if r[READ_KIND] == HIT else 2, (p - 0.5) * 2, colour))
        ended = [r for r in run.rows("reads", t - BACK - run.max_dur.get("reads", 0.0), t + 1e-9)
                 if t - BACK <= r[READ_END] <= t and not r[READ_OK]]
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
