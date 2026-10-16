"""The pictures for lab keyset_pagination: lanes (clients, the API as the door, the database as the
server) and cluster (clients -> three API servers -> the database's 4 workers)."""

from __future__ import annotations

from labs.keyset_pagination import lab
from labs.keyset_pagination.api import WORKERS
from labs.keyset_pagination.scenario import APIS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every, just_sent, user_flights, user_outcomes
from live.canvas import BLUE, DIM, EXTRA, EXTRA2, GREEN, PURPLE, RED
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


def _state(w, run, variant: str, t: float):
    """What the feed is going through: (words, colour), the pages that came back in the last second,
    and the database's busy share in that second."""
    from live.worlds.keyset_pagination import P_DUP, P_READ, P_SKIPPED, Q_END, Q_START

    last = w.ended(run, t - 1, t + 1e-9)
    span = run.max_dur.get("queries", 0.0)
    busy = sum(min(q[Q_END], t) - max(q[Q_START], t - 1)
               for q in run.rows("queries", t - 1 - span, t) if q[Q_END] > t - 1) / WORKERS
    inc = w.incident_at(variant, t)
    if any(p[P_SKIPPED] for p in last):
        state = (w.s("state_skipping"), RED)
    elif any(p[P_DUP] for p in last):
        state = (w.s("state_repeating"), PURPLE)
    elif any(p[P_READ] > lab.BUCKETS[-1] for p in last):
        state = (w.s("state_scans"), EXTRA2)
    elif inc is not None:
        state = (w.s(f"state_{inc.kind}"), BLUE)
    else:
        state = (w.screen.STATES["healthy"], GREEN)
    return state, last, busy


def _outcomes(w, run, t: float) -> list:
    """Pages fading at the door: wrong ones first, so a few among many still show."""
    from live.worlds.keyset_pagination import P_END, page_colour

    return user_outcomes(w.ended(run, t - BACK, t + 1e-9), t, P_END, page_colour,
                         rare=lambda p: page_colour(p) != GREEN)


@adapts("keyset_pagination", "lanes")
class KeysetPaginationLanes(LaneAdapter):
    """Each page request is a client; it flies to the API coloured by how many rows the database read
    for it (white about a page, deeper orange for OFFSET's skipped rows; a big dot past 4,000). At the
    door: green a right page, red a page that jumped past posts, purple one that repeated posts, grey a
    400. The database's gauge is its busy share of 4 workers."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.keyset_pagination import P_END, P_ID, P_READ, P_START, cost_colour

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(p[P_ID], users): (cost_colour(p[P_READ]), True) for p in run.active("pages", t, P_END)}
        flying = just_sent(run, "pages", t)
        flights = user_flights(every(flying, FLIGHTS), t, P_START,
                               lambda p: (slot(p[P_ID], users), cost_colour(p[P_READ]), p[P_READ] > lab.BUCKETS[-1]))
        state, last, busy = _state(w, run, variant, t)
        wrong = state[1] in (RED, PURPLE)
        return LaneFrame(
            users=found, flights=flights, outcomes=_outcomes(w, run, t),
            door_color=state[1] if wrong else None,  # the API hands out the wrong page here
            fill=min(1.0, busy), gauge=EXTRA2 if busy > 0.5 else BLUE,
            outline=EXTRA2 if busy > 0.8 else OUTLINE, state=state,
        )


@adapts("keyset_pagination", "cluster")
class KeysetPaginationCluster(ClusterAdapter):
    """The topology: clients -> three API servers (nodes 0-2), each with its own FeedAPI -> the
    database's 4 workers (nodes 3-6).

    A page request flies from the clients to its API server, then its query on to the worker that
    runs it, coloured by the rows it reads: white about a page, deeper orange for OFFSET's thousands.
    A worker is coloured by the query it runs right now (dim while idle): a deep OFFSET keeps one deep
    orange, an index seek is gone in a blink. A page that skipped posts flies back to the clients in
    red, one that repeated posts in purple. The line under the grid says the rows read per page.
    """

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.keyset_pagination import (
            P_API, P_END, P_ID, P_READ, P_START, Q_END, Q_PAGE, Q_READ, Q_WORKER, cost_colour, page_colour,
            rows_text,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        span = run.max_dur.get("queries", 0.0)
        running = [q for q in run.rows("queries", t - span - 1e-9, t + 1e-9) if q[Q_END] > t]
        workers = [DIM] * WORKERS
        for q in running:
            workers[q[Q_WORKER]] = cost_colour(q[Q_READ])
        worker_of = {q[Q_PAGE]: q[Q_WORKER] for q in run.rows("queries", t - FLY - span - 1, t + 1e-9)}

        flights = []
        for p in every(just_sent(run, "pages", t), FLIGHTS):
            f = (t - p[P_START]) / FLY
            colour = cost_colour(p[P_READ])
            if f < 0.5:  # into its API server
                flights.append((-1, p[P_API], 2 * f, EXTRA[0]))
            else:  # its query, on to the worker that runs it
                flights.append((p[P_API], APIS + worker_of.get(p[P_ID], p[P_ID] % WORKERS), 2 * f - 1, colour))
        wrong = [p for p in w.ended(run, t - BACK, t + 1e-9) if page_colour(p) in (RED, PURPLE)]
        flights += [(p[P_API], -1, (t - p[P_END]) / BACK, page_colour(p)) for p in every(wrong, OUTCOMES)]

        state, last, busy = _state(w, run, variant, t)
        apis = [BLUE] * APIS
        for p in last:
            if page_colour(p) in (RED, PURPLE):
                apis[p[P_API]] = page_colour(p)
        rows = sum(p[P_READ] for p in last) / len(last) if last else 0.0
        return ClusterFrame(nodes=apis + workers, flights=flights,
                            state=(w.s("pic_state", rows=rows_text(rows), state=state[0]), state[1]))
