"""The pictures for lab message_queue_consumers: cluster (the queue, seven worker processes and the
dead-letter queue as nodes), lanes (the messages on the left, the queue as the door, the workers
as the server) and relay (producers → the queue as a server of its own → the workers)."""

from __future__ import annotations

from labs.message_queue_consumers import lab as mq
from labs.message_queue_consumers.scenario import FAILED, LOST, OK, PARKED
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame

OLD = 20.0  # seconds: a message this old is stuck (poison retried forever; the DLQ takes ~15 s)


def _state(w, run, variant: str, t: float, down: set[int]):
    """The word under the picture, and its colour."""
    from live.worlds.message_queue_consumers import DEP_OLDEST

    inc = w.incident_at(variant, t)
    dep = w.depth_at(run, t)
    words = w.screen.STATES
    if down:
        return w.s("state_down", n=len(down)), RED
    if dep is not None and dep[DEP_OLDEST] > OLD:
        return w.s("state_old"), EXTRA2
    if inc is not None and inc.kind in ("slow", "poison", "blip"):
        return w.s(f"state_{inc.kind}"), EXTRA2
    return words["healthy"], GREEN


def _ended(w, run, t: float) -> list[tuple]:
    """Tries that ended in the last BACK seconds."""
    from live.worlds.message_queue_consumers import TRY_END

    span = run.max_dur.get("tries", 0.0)
    return [r for r in run.rows("tries", t - BACK - span, t + 1e-9) if t - BACK <= r[TRY_END] <= t]


def _outcome(r: tuple, jobs: dict[int, tuple]):
    """What a try's end looked like: acked (green), back to the queue (orange), parked (purple),
    lost (red), or killed by a crash (grey)."""
    from live.worlds.message_queue_consumers import JOB_END, JOB_OUTCOME, TRY_END, TRY_ID, TRY_RESULT

    job = jobs.get(r[TRY_ID])
    final = job is not None and job[JOB_END] is not None and abs(job[JOB_END] - r[TRY_END]) < 0.05
    if final and job[JOB_OUTCOME] == LOST:
        return RED
    if final and job[JOB_OUTCOME] == PARKED:
        return PURPLE
    if r[TRY_RESULT] == OK:
        return GREEN
    if r[TRY_RESULT] == FAILED:
        return EXTRA2
    return MUTED


def _jobs_of(run, rows: list[tuple]) -> dict[int, tuple]:
    from live.worlds.message_queue_consumers import JOB_ID, TRY_ID, TRY_START

    if not rows:
        return {}
    a = min(r[TRY_START] for r in rows) - run.max_dur.get("jobs", 0.0) - 1.0
    ids = {r[TRY_ID] for r in rows}
    return {j[JOB_ID]: j for j in run.rows("jobs", a, max(r[TRY_START] for r in rows) + 1e-9) if j[JOB_ID] in ids}


@adapts("message_queue_consumers", "cluster")
class QueueCluster(ClusterAdapter):
    """The queue (left, middle), seven worker processes around it and the DLQ (right, middle).

    Producers send messages to the queue (white). Each delivery flies to a worker, coloured by its
    try (white first, oranges redelivered, deep orange when a second worker takes a job another one
    is still on). When a job ends the ack flies back to the queue: green done, orange failed (the
    message waits to come back); a parked message flies on to the DLQ (purple); a lost job dies in
    red. A worker is orange while busy and red while it is down; the queue turns orange, then red,
    as its oldest message gets older.
    """

    QUEUE, DLQ = 3, 5
    WORKERS = (0, 1, 2, 4, 6, 7, 8)

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.message_queue_consumers import (
            DEP_OLDEST, JOB_SENT, TRY_END, TRY_ID, TRY_PROC, TRY_START, try_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights: list[tuple] = []
        drops: list[tuple] = []
        flights += [(-1, self.QUEUE, (t - j[JOB_SENT]) / FLY, WHITE)
                    for j in every(run.rows("jobs", t - FLY, t + 1e-9), FLIGHTS)]
        flights += [(self.QUEUE, self.WORKERS[r[TRY_PROC]], (t - r[TRY_START]) / FLY, try_colour(r))
                    for r in every(run.rows("tries", t - FLY, t + 1e-9), FLIGHTS)]
        ended = _ended(w, run, t)
        jobs = _jobs_of(run, ended)
        for r in every(ended, OUTCOMES * 2):
            colour = _outcome(r, jobs)
            p = (t - r[TRY_END]) / BACK
            node = self.WORKERS[r[TRY_PROC]]
            if colour == RED:
                drops.append((node, self.QUEUE, p))
            elif colour == PURPLE:
                flights.append((node, self.DLQ, p, PURPLE))
            elif colour != MUTED:
                flights.append((node, self.QUEUE, p, colour))

        down = w.down_at(run, t)
        busy = w.busy_at(run, t)
        nodes = [BLUE] * 9
        for i, n in enumerate(self.WORKERS):
            jobs_on = busy.get(i, 0)
            nodes[n] = RED if i in down else BLUE if jobs_on == 0 else EXTRA1 if jobs_on < 3 else \
                EXTRA2 if jobs_on < mq.SLOTS else EXTRA3
        dep = w.depth_at(run, t)
        oldest = dep[DEP_OLDEST] if dep else 0.0
        nodes[self.QUEUE] = RED if oldest > OLD else EXTRA2 if oldest > mq.AGE_MAX else BLUE
        parked = run.total("parked", t + 1)
        nodes[self.DLQ] = PURPLE if parked else MUTED
        word, colour = _state(w, run, variant, t, down)
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops,
                            state=(w.s("pic_state", state=word), colour))


@adapts("message_queue_consumers", "lanes")
class QueueLanes(LaneAdapter):
    """Each message is a circle on the left, filled while it is in the queue or being worked on:
    white on its first delivery, oranges once redelivered, deep orange while two workers have it,
    red when it has been in the queue for over 20 s (poison going round forever). Deliveries fly to
    the door (the queue); what happened fades there: green acked, orange failed, purple parked, red
    lost. The server is the worker pool: its gauge is the share of slots busy, red while processes
    are down."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.message_queue_consumers import (
            JOB_END, JOB_ID, JOB_RECEIVES, JOB_SENT, TRY_END, TRY_ID, TRY_N, TRY_START, try_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        span = run.max_dur.get("jobs", 0.0)
        found: dict[int, tuple] = {}
        live = [j for j in run.rows("jobs", t - span - 1e-9, t + 1e-9) if j[JOB_END] is None or j[JOB_END] > t]
        live += [j for j in w.stuck(run) if j[JOB_SENT] < t - span]  # still going round, from long ago
        tries = {}
        for r in run.rows("tries", t - span - 1e-9, t + 1e-9):
            tries[r[TRY_ID]] = r
        for j in live:
            r = tries.get(j[JOB_ID])
            if t - j[JOB_SENT] > OLD:
                colour = RED
            elif r is not None:
                colour = try_colour(r)
            else:  # waiting for its next delivery
                colour = WHITE if j[JOB_RECEIVES] <= 1 else EXTRA1
            found[slot(j[JOB_ID], users)] = (colour, True)

        flying = run.rows("tries", t - FLY, t + 1e-9)
        flights = [(slot(r[TRY_ID], users), (t - r[TRY_START]) / FLY, try_colour(r), r[TRY_N] > 1)
                   for r in every(flying, FLIGHTS)]
        ended = _ended(w, run, t)
        jobs = _jobs_of(run, ended)
        coloured = [(_outcome(r, jobs), (t - r[TRY_END]) / BACK) for r in ended]
        rare = every([o for o in coloured if o[0] in (RED, PURPLE)], OUTCOMES)  # a few lost among many acked
        room = OUTCOMES - len(rare)
        outcomes = rare + (every([o for o in coloured if o[0] not in (RED, PURPLE)], room) if room else [])

        down = w.down_at(run, t)
        busy = sum(w.busy_at(run, t).values())
        slots = (mq.PROCESSES - len(down)) * mq.SLOTS
        word, colour = _state(w, run, variant, t, down)
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=EXTRA2 if colour == EXTRA2 else None,
            fill=busy / max(1, mq.PROCESSES * mq.SLOTS),
            gauge=EXTRA2 if slots and busy / slots > 0.8 else BLUE,
            outline=RED if down else OUTLINE, state=(word, colour),
        )


QUEUE_FULL = mq.PROCESSES * mq.SLOTS  # messages in the queue (waiting or hidden) that fill its gauge


def _poison_back(run, t: float) -> int:
    """Poison messages back in the queue at t: a try of theirs has failed, and the job is not over."""
    from live.worlds.message_queue_consumers import JOB_END, TRY_END, TRY_ID, TRY_POISON

    span = run.max_dur.get("tries", 0.0) + run.max_dur.get("jobs", 0.0)
    failed = [r for r in run.rows("tries", t - span - 1e-9, t + 1e-9) if r[TRY_POISON] and r[TRY_END] <= t]
    jobs = _jobs_of(run, failed)
    return len({r[TRY_ID] for r in failed
                if (j := jobs.get(r[TRY_ID])) is not None and (j[JOB_END] is None or j[JOB_END] > t)})


@adapts("message_queue_consumers", "relay")
class QueueRelay(RelayAdapter):
    """The lanes picture with the queue as a server of its own: producers → the door → the queue → the worker
    pool. New messages fly from the producers to the door (white). The queue's gauge is how many messages it
    holds (waiting, or hidden while a worker has them), blue while the oldest is under 1 s old, orange over it,
    red over 20 s; its outline turns purple while poison that failed is back in it waiting to come round again,
    and its label counts the messages parked in the DLQ. Deliveries fly from the queue to the workers: white the
    first, oranges redelivered, deep orange a job a second worker takes while another is still on it; poison
    flies big. A job lost at the workers (acked, then crashed or failed) sits red at their door. The server on
    the right is the worker pool, as in the lanes picture."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.message_queue_consumers import (
            DEP_INFLIGHT, DEP_OLDEST, DEP_VISIBLE, JOB_ID, JOB_SENT, TRY_END, TRY_POISON, TRY_START, try_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = QueueLanes(w).frame(variant, t, users)  # the messages, the outcomes and the workers, as in lanes
        flights = [(slot(j[JOB_ID], users), (t - j[JOB_SENT]) / FLY, WHITE, False)
                   for j in every(run.rows("jobs", t - FLY, t + 1e-9), FLIGHTS)]
        flying = run.rows("tries", t - FLY, t + 1e-9)
        rare = every([r for r in flying if r[TRY_POISON]], FLIGHTS // 2)  # a few poison among many good
        shown = rare + every([r for r in flying if not r[TRY_POISON]], FLIGHTS - len(rare))
        hops = [((t - r[TRY_START]) / FLY, try_colour(r), bool(r[TRY_POISON])) for r in shown]
        ended = _ended(w, run, t)
        gone = _jobs_of(run, ended)
        for r in every([r for r in ended if _outcome(r, gone) == RED], OUTCOMES):  # lost at the workers' door
            hops.append((0.9 + 0.1 * (t - r[TRY_END]) / BACK, RED, True))

        dep = w.depth_at(run, t)
        held = (dep[DEP_VISIBLE] + dep[DEP_INFLIGHT]) if dep else 0
        oldest = dep[DEP_OLDEST] if dep else 0.0
        parked = int(run.total("parked", t + 1))
        poison = _poison_back(run, t)
        gauge = RED if oldest > OLD else EXTRA2 if oldest > mq.AGE_MAX else BLUE
        relay = Relay(label=(w.s("relay_queue", n=parked), PURPLE if parked else OUTLINE),
                      fill=held / QUEUE_FULL, gauge=gauge, outline=PURPLE if poison else OUTLINE)
        return RelayFrame(users=lane.users, flights=flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, fill=lane.fill, gauge=lane.gauge, outline=lane.outline,
                          state=lane.state, relay=relay, hops=hops)
