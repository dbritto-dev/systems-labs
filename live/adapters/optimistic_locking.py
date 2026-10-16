"""The pictures for lab optimistic_locking: lanes (users, the API as the door, the stock database as the
server) and cluster (users -> three app servers -> one stock database)."""

from __future__ import annotations

from labs.optimistic_locking.api import CLOBBER, CONFLICT as W_CONFLICT
from labs.optimistic_locking.scenario import APPS, CONFLICT, OK
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every, just_ended, just_sent, user_flights, user_outcomes
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, MUTED, RED
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

WRITES_MAX = 400.0  # writes a second that fill the database's gauge


def _state(w, run, variant: str, t: float):
    """What the database is going through: (words, colour), and whether updates were lost or
    conflicted in the last second."""
    from live.worlds.optimistic_locking import W_END, W_RESULT

    span = run.max_dur.get("writes", 0.0)
    last = [x for x in run.rows("writes", t - 1 - span, t + 1e-9) if t - 1 <= x[W_END] <= t]
    lost = any(x[W_RESULT] == CLOBBER for x in last)
    stale = any(x[W_RESULT] == W_CONFLICT for x in last)
    inc = w.incident_at(variant, t)
    if lost:
        state = (w.s("state_lost"), RED)
    elif inc is not None and inc.kind == "flash":
        state = (w.s("state_hot"), EXTRA2)
    elif inc is not None and inc.kind == "slow":
        state = (w.s("state_slow"), EXTRA2)
    elif stale:
        state = (w.s("state_conflicts"), EXTRA2)
    elif inc is not None:
        state = (w.screen.STATES["busy"], EXTRA2)
    else:
        state = (w.screen.STATES["healthy"], GREEN)
    return state, lost, stale, len(last)


@adapts("optimistic_locking", "lanes")
class OptimisticLockingLanes(LaneAdapter):
    """Each request is a user; each write it sends flies to the API (white the first, deeper orange for
    each retry). At the door: green served, orange a 409, red a write that erased other updates, grey a
    user who gave up waiting. The database's gauge is its writes per second."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.optimistic_locking import (
            REQ_END, REQ_ID, REQ_LOST, REQ_OUTCOME, W_N, W_REQ, W_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        span = run.max_dur.get("writes", 0.0) + 0.1
        tries: dict[int, int] = {}
        for x in run.rows("writes", t - span - 2, t + 1e-9):
            tries[x[W_REQ]] = max(tries.get(x[W_REQ], 0), x[W_N])
        found = {slot(r[REQ_ID], users): (EXTRA[min(3, tries.get(r[REQ_ID], 0))], True)
                 for r in run.active("requests", t, REQ_END)}
        flying = just_sent(run, "writes", t)
        flights = user_flights(every(flying, FLIGHTS), t, W_START,
                               lambda x: (slot(x[W_REQ], users), EXTRA[min(3, x[W_N])], x[W_N] > 0))
        ended = just_ended(run, "requests", REQ_END, t)

        def colour(r: tuple):
            if r[REQ_LOST]:
                return RED
            return GREEN if r[REQ_OUTCOME] == OK else EXTRA2 if r[REQ_OUTCOME] == CONFLICT else MUTED

        # A few red or orange answers among hundreds of green ones still reach the door.
        outcomes = user_outcomes(ended, t, REQ_END, colour, rare=lambda r: colour(r) != GREEN)

        state, lost, stale, writes = _state(w, run, variant, t)
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=EXTRA2 if stale else None,  # the API answers 409s here
            fill=writes / WRITES_MAX, gauge=RED if lost else EXTRA2 if stale else BLUE,
            outline=RED if lost else OUTLINE, state=state,
        )


@adapts("optimistic_locking", "cluster")
class OptimisticLockingCluster(ClusterAdapter):
    """The topology: users -> three app servers (nodes 0-2), each with its own StockService -> one stock
    database (node 3).

    A request flies from the users to its app server (white). Its writes fly on to the database: white
    when they commit, orange when the version no longer matches (a conflict; the row was not touched),
    red when a plain write erased updates it never read (a lost update). A 409 flies back to the users
    in orange. An app server turns orange while it is retrying; the database turns red when an update
    was just lost and orange while writes conflict.
    """

    DB = APPS

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.optimistic_locking import (
            REQ_APP, REQ_END, REQ_OUTCOME, REQ_START, W_APP, W_N, W_RESULT, W_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = []
        for r in every(run.rows("requests", t - FLY / 2, t + 1e-9), FLIGHTS):  # into the app servers
            flights.append((-1, r[REQ_APP], (t - r[REQ_START]) / (FLY / 2), EXTRA[0]))
        retrying = set()
        for x in every(run.rows("writes", t - FLY, t - FLY / 2 + 1e-9), FLIGHTS):  # on to the database
            p = (t - FLY / 2 - x[W_START]) / (FLY / 2)
            colour = RED if x[W_RESULT] == CLOBBER else EXTRA2 if x[W_RESULT] == W_CONFLICT else EXTRA[min(3, x[W_N])]
            flights.append((x[W_APP], self.DB, p, colour))
            if x[W_N] > 0:
                retrying.add(x[W_APP])
        refused = [r for r in just_ended(run, "requests", REQ_END, t) if r[REQ_OUTCOME] == CONFLICT]
        flights += [(r[REQ_APP], -1, (t - r[REQ_END]) / BACK, EXTRA2) for r in every(refused, OUTCOMES)]

        state, lost, stale, _ = _state(w, run, variant, t)
        apps = [EXTRA2 if k in retrying else BLUE for k in range(APPS)]
        db = RED if lost else EXTRA2 if stale else BLUE
        return ClusterFrame(nodes=apps + [db], flights=flights,
                            state=(w.s("pic_state", state=state[0]), state[1]))
