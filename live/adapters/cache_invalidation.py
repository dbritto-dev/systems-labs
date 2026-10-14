"""The pictures for lab cache_invalidation: lanes (users -> the cache as the door -> the database as the
server) and cluster (users -> three app servers -> one cache and one database)."""

from __future__ import annotations

from labs.cache_invalidation import lab
from labs.cache_invalidation.api import FILLED_STALE, REFUSED
from labs.cache_invalidation.scenario import APPS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


def _state(w, run, variant: str, t: float):
    """What the cache and the database are going through: (words, colour), the stale keys in the
    cache, whether the cache is down, and the database's reads in the last second."""
    from live.worlds.cache_invalidation import A_DB, A_STALE, A_UP

    audit = w.audit_at(run, t)
    stale = audit[A_STALE] if audit else 0
    reads = audit[A_DB] if audit else 0
    inc = w.incident_at(variant, t)
    down = (inc is not None and inc.kind == "restart" and t < inc.t1) or (audit is not None and not audit[A_UP])
    if stale:
        state = (w.s("state_stale", n=stale), RED)
    elif down:
        state = (w.s("state_down"), EXTRA2)
    elif inc is not None and inc.kind == "slow":
        state = (w.s("state_slow"), EXTRA2)
    elif inc is not None and inc.kind in ("campaign", "import"):
        state = (w.s("state_writes"), EXTRA2)
    else:
        state = (w.screen.STATES["healthy"], GREEN)
    return state, stale, down, reads


def _db_colour(reads: float):
    return RED if reads > lab.DB_LIMIT else EXTRA2 if reads > 0.6 * lab.DB_LIMIT else BLUE


@adapts("cache_invalidation", "lanes")
class CacheInvalidationLanes(LaneAdapter):
    """Each read is a user; it flies to the cache (the door): white when the cache has it, orange when it
    missed and went on to the database (the server). Writes fly in blue. At the door: green a fresh
    read, red a stale one (or a price that was never saved). The door turns red while the cache holds
    stale keys, orange while it restarts. The database's gauge is its reads per second."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.cache_invalidation import R_END, R_FRESH, R_ID, R_MISSED, R_START, W_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(r[R_ID], users): (EXTRA1 if r[R_MISSED] else WHITE, True)
                 for r in run.active("reads", t, R_END)}
        flying = run.rows("reads", t - FLY, t + 1e-9)
        flights = [(slot(r[R_ID], users), (t - r[R_START]) / FLY, EXTRA1 if r[R_MISSED] else WHITE, r[R_MISSED])
                   for r in every(flying, FLIGHTS - 3)]
        writes = run.rows("writes", t - FLY, t + 1e-9)
        flights += [(slot(int(x[W_START] * 1_000_003), users), (t - x[W_START]) / FLY, BLUE, False)
                    for x in every(writes, 3)]
        span = run.max_dur.get("reads", 0.0)
        ended = [r for r in run.rows("reads", t - BACK - span, t + 1e-9) if t - BACK <= r[R_END] <= t]
        # A few red answers among hundreds of green ones still reach the door.
        bad = every([r for r in ended if not r[R_FRESH]], OUTCOMES)
        shown = bad + every([r for r in ended if r[R_FRESH]], OUTCOMES - len(bad))
        outcomes = [(GREEN if r[R_FRESH] else RED, (t - r[R_END]) / BACK) for r in shown]

        state, stale, down, reads = _state(w, run, variant, t)
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=RED if stale else EXTRA2 if down else None,  # the cache
            fill=reads / lab.GAUGE_MAX, gauge=_db_colour(reads), outline=OUTLINE, state=state,
        )


@adapts("cache_invalidation", "cluster")
class CacheInvalidationCluster(ClusterAdapter):
    """The topology: users -> three app servers (nodes 0-2, top row) -> the cache (node 3) and the
    database (node 4) below them.

    A read flies from the users to its app server, then to the cache (white, a hit) or to the database
    (orange, a miss). After a miss the app server fills the cache: white when the record is current,
    red when it is already older than the database's (a stale fill: it undoes a delete), orange when
    the cache refuses it (a lease that a delete made invalid). Writes fly in blue to the database and
    then to the cache (the delete). An app server turns orange during a GC pause; the cache turns red
    while it holds stale keys and orange while it restarts; the database turns orange, then red, as
    its reads per second near the limit.
    """

    CACHE, DB = APPS, APPS + 1

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.cache_invalidation import (
            F_APP, F_RESULT, F_T, P_APP, P_T0, P_T1, R_APP, R_MISSED, R_START, W_APP, W_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        half = FLY / 2
        flights = []
        for r in every(run.rows("reads", t - FLY, t + 1e-9), FLIGHTS - 4):
            p = (t - r[R_START]) / half
            colour = EXTRA1 if r[R_MISSED] else WHITE
            if p < 1:  # into the app server
                flights.append((-1, r[R_APP], p, colour))
            else:  # on to the cache (a hit) or the database (a miss)
                flights.append((r[R_APP], self.DB if r[R_MISSED] else self.CACHE, p - 1, colour))
        for x in every(run.rows("writes", t - FLY, t + 1e-9), 2):
            p = (t - x[W_START]) / half
            flights.append((x[W_APP], self.DB, p, BLUE) if p < 1 else (x[W_APP], self.CACHE, p - 1, BLUE))
        fills = run.rows("fills", t - half, t + 1e-9)
        rare = [f for f in fills if f[F_RESULT] != 0]
        shown = every(rare, 4) + every([f for f in fills if f[F_RESULT] == 0], 4 - min(4, len(rare)))
        for f in shown:
            colour = RED if f[F_RESULT] == FILLED_STALE else EXTRA2 if f[F_RESULT] == REFUSED else WHITE
            flights.append((f[F_APP], self.CACHE, (t - f[F_T]) / half, colour))

        paused = {p[P_APP] for p in run.rows("pauses", t - 1.0, t + 1e-9) if p[P_T0] <= t < p[P_T1]}
        state, stale, down, reads = _state(w, run, variant, t)
        apps = [EXTRA2 if k in paused else BLUE for k in range(APPS)]
        cache = RED if stale else EXTRA2 if down else BLUE
        return ClusterFrame(nodes=apps + [cache, _db_colour(reads)], flights=flights,
                            state=(w.s("pic_state", state=state[0]), state[1]))
