"""The pictures for lab overload: lanes (the door is the queue, the server's gauge is how many wait
in it) and cluster (the topology: clients → queue → server)."""

from __future__ import annotations

from labs.overload import lab as overload_lab
from labs.overload.scenario import LATE, OK, REJECTED
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot


@adapts("overload", "lanes")
class OverloadLanes(LaneAdapter):
    """Users wait in a queue (deeper orange for each retry); the door shuts while the queue is full
    and rejects; the server's gauge is the queue, orange while it works for users who already left."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.overload import (
            REQ_CLIENT, REQ_DONE, TRIES, TRY_ATTEMPT, TRY_CLIENT, TRY_END, TRY_RESULT, TRY_SENT, WORK_END,
            WORK_KIND, capacity_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        # Users still waiting, coloured by which try they are on.
        latest: dict[int, int] = {}
        for r in run.rows("tries", t - 3.5, t + 1e-9):
            latest[r[TRY_CLIENT]] = max(latest.get(r[TRY_CLIENT], 0), r[TRY_ATTEMPT])
        found = {slot(q[REQ_CLIENT], users): (TRIES[min(2, latest.get(q[REQ_CLIENT], 0))], True)
                 for q in run.active("requests", t, REQ_DONE)}

        # Tries flying to the door, and what came back: in time, rejected, or work wasted on a user who left.
        flying = run.rows("tries", t - FLY, t + 1e-9)
        flights = [(slot(r[TRY_CLIENT], users), (t - r[TRY_SENT]) / FLY, TRIES[min(2, r[TRY_ATTEMPT])],
                    r[TRY_ATTEMPT] > 0) for r in every(flying, FLIGHTS)]
        answered = [r for r in run.rows("tries", t - BACK - 1.0, t + 1e-9)
                    if t - BACK <= r[TRY_END] <= t and r[TRY_RESULT] in (OK, REJECTED)]
        wasted = [x for x in run.rows("work", t - BACK, t + 1e-9) if x[WORK_KIND] == LATE and x[WORK_END] <= t]
        outcomes = [(GREEN if r[TRY_RESULT] == OK else RED, (t - r[TRY_END]) / BACK) for r in answered]
        outcomes += [(EXTRA3, (t - x[WORK_END]) / BACK) for x in wasted]
        outcomes = every(outcomes, OUTCOMES)

        waiting, stale = w.queue_at(run, t)
        rejecting = any(r[TRY_RESULT] == REJECTED for r in run.rows("tries", t - 0.5, t + 1e-9))
        recent = run.rows("work", t - 1.0, t + 1e-9)
        late = sum(x[WORK_KIND] == LATE for x in recent)
        busy = sum(x[WORK_KIND] != 2 for x in recent)
        words = w.screen.STATES
        if busy and late / busy > 0.5:
            state, outline = (w.s("state_wasting"), EXTRA2), EXTRA2
        elif waiting > 100 or capacity_at(run, t) < overload_lab.CAPACITY:
            state, outline = (words["overloaded"], RED), RED
        else:
            state, outline = (words["healthy"], GREEN), OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=rejecting,
            fill=waiting / overload_lab.QUEUE_SHOWN,
            gauge=EXTRA2 if waiting and stale / waiting > 0.5 else BLUE,
            outline=outline, state=state,
        )


@adapts("overload", "cluster")
class OverloadCluster(ClusterAdapter):
    """The topology, live: clients → the queue → the server.

    Tries fly from the clients to the queue (deeper orange for each retry); work flies from the
    queue to the server, deep orange when it is for a user who already left. A full queue rejects:
    the try dies in red on the way in. The queue node is orange while users wait in it (deeper the
    more of them already left); the server turns red while it has lost capacity.
    """

    QUEUE, SERVER = 0, 1

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.overload import (
            TRIES, TRY_ATTEMPT, TRY_END, TRY_RESULT, TRY_SENT, WORK_END, WORK_KIND, WORK_START, capacity_at,
        )
        from labs.overload.scenario import SKIPPED

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = [(-1, self.QUEUE, (t - r[TRY_SENT]) / FLY, TRIES[min(2, r[TRY_ATTEMPT])])
                   for r in every(run.rows("tries", t - FLY, t + 1e-9), FLIGHTS)]
        work = [x for x in run.rows("work", t - FLY, t + 1e-9) if x[WORK_KIND] != SKIPPED]
        flights += [(self.QUEUE, self.SERVER, (t - x[WORK_START]) / FLY, EXTRA3 if x[WORK_KIND] == LATE else WHITE)
                    for x in every(work, FLIGHTS)]
        rejected = [r for r in run.rows("tries", t - BACK - 1.0, t + 1e-9)
                    if t - BACK <= r[TRY_END] <= t and r[TRY_RESULT] == REJECTED]
        drops = [(-1, self.QUEUE, (t - r[TRY_END]) / BACK) for r in every(rejected, OUTCOMES)]

        waiting, stale = w.queue_at(run, t)
        if waiting > 100:
            queue = RED
        elif waiting:
            queue = EXTRA3 if stale / waiting > 0.5 else EXTRA2 if waiting > 20 else EXTRA1
        else:
            queue = BLUE
        recent = run.rows("work", t - 1.0, t + 1e-9)
        late = sum(x[WORK_KIND] == LATE for x in recent)
        busy = sum(x[WORK_KIND] != SKIPPED for x in recent)
        lost = capacity_at(run, t) < overload_lab.CAPACITY
        server = RED if lost else EXTRA3 if busy and late / busy > 0.5 else BLUE
        words = w.screen.STATES
        if busy and late / busy > 0.5:
            word, colour = w.s("state_wasting"), EXTRA2
        elif waiting > 100 or lost:
            word, colour = words["overloaded"], RED
        else:
            word, colour = words["healthy"], GREEN
        return ClusterFrame(nodes=[queue, server], flights=flights, drops=drops,
                            state=(f"{word}   {w.s('topology')}", colour))
