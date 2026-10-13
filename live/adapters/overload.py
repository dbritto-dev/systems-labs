"""The lanes picture for lab overload: the door is the queue, the server's gauge is how many wait in it."""

from __future__ import annotations

from labs.overload import lab as overload_lab
from labs.overload.scenario import LATE, OK, REJECTED
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, RED
from live.views.base import adapts
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
