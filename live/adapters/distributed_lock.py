"""The pictures for lab distributed_lock: cluster (the lock service, 4 workers and the storage, with the
lock's messages and the writes in flight) and lanes (jobs waiting for the lock, the door, in front of the
storage)."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

DROP_FADE = 0.6  # seconds a dropped message stays on screen
BURST = 0.8  # seconds a corrupt or refused write stays by the storage
JOB_SHOWN = 0.15  # a job flies to its worker this long (cosmetic)
MIN_FLIGHT = 0.12  # a message is on screen at least this long (they take ~50 ms: too quick to see)
MAX_FLIGHTS = 80
HELD = 0.08  # where a write held by a frozen worker waits: just outside it


def _flight(t: float, sent: float, arrived: float) -> float | None:
    """How far along a message is at t, stretched to at least MIN_FLIGHT; None when not in flight."""
    span = max(MIN_FLIGHT, arrived - sent)
    return None if not sent <= t < sent + span else (t - sent) / span


@adapts("distributed_lock", "cluster")
class DistributedLockCluster(ClusterAdapter):
    """The lock service (top left), the storage (bottom left) and workers w1..w4.

    Lock traffic (acquire, renew, release and their answers) flies in blue; writes fly from a worker to
    the storage in white, light orange while one sits in the network. The holder of the lock is green; a
    frozen worker is orange and its writes wait just outside it; a crashed or cut-off one is red. A write
    from a lost lock that the storage accepted bursts red by it, and orange if the storage refused it.
    """

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.distributed_lock import lab
        from labs.distributed_lock.scenario import LOCK, LOCK_MSG, STORAGE
        from live.worlds.distributed_lock import (
            JOB_START, JOB_WORKER, MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, SLOW_STALL, W_ARRIVED,
            W_LEFT, W_WORKER, corrupt, name, refused, stall_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for r in run.rows("jobs", t - JOB_SHOWN, t + 1e-9):  # jobs handed to a worker
            flights.append((-1, r[JOB_WORKER], min(1.0, (t - r[JOB_START]) / JOB_SHOWN), WHITE))
        for m in run.rows("msgs", t - DROP_FADE - 1, t + 1e-9):
            if m[MSG_ARRIVED] is None:
                if t - m[MSG_SENT] < DROP_FADE:
                    drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
                continue
            p = _flight(t, m[MSG_SENT], m[MSG_ARRIVED])
            if p is not None:
                flights.append((m[MSG_SRC], m[MSG_DEST], p, BLUE if m[MSG_KIND] == LOCK_MSG else DIM))
        span = run.max_dur.get("writes", 0.0)
        for x in run.rows("writes", t - span - BURST - 1e-9, t + 1e-9):
            src = x[W_WORKER]
            if t < x[W_LEFT]:  # held by a frozen worker
                flights.append((src, STORAGE, HELD, EXTRA2))
                continue
            p = _flight(t, x[W_LEFT], x[W_ARRIVED])
            if p is not None:
                late = x[W_ARRIVED] - x[W_LEFT] > 1.0  # it sits in the network
                flights.append((src, STORAGE, min(p, 0.95), EXTRA1 if late else WHITE))
            elif x[W_ARRIVED] <= t < x[W_ARRIVED] + BURST and (corrupt(x) or refused(x)):
                colour = RED if corrupt(x) else EXTRA2
                for d in (0.86, 0.9, 0.94):  # a burst by the storage
                    flights.append((src, STORAGE, d, colour))

        stuck = stall_at(run, t)
        recent = w.recent_writes(run, t)
        nodes = [BLUE] * 6
        nodes[LOCK] = RED if stuck > lab.STUCK_MAX else EXTRA2 if stuck > SLOW_STALL else BLUE
        nodes[STORAGE] = RED if any(map(corrupt, recent)) else EXTRA2 if any(map(refused, recent)) else BLUE
        holder = w.holder_at(run, t)
        if holder is not None:
            nodes[holder[1]] = GREEN
        sick = w.sick_at(variant, t)
        if sick is not None and sick[1] != "delay":
            nodes[sick[0]] = EXTRA2 if sick[1] == "pause" else RED
        text, colour = w.state_at(variant, t)
        lock = w.s("state_lock", worker=w.s("nobody") if holder is None else name(holder[1]))
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 30),
                            state=(f"{text}   {lock}", colour))


# ---------------------------------------------------------------- the lanes picture: the jobs' view

WAITED = (1.5, 3.0, 6.0)  # seconds a job has waited before it turns light, mid, deep orange (a job takes ~0.7 s)
GAUGE_MAX = 6.0  # accepted writes per second that fill the gauge


@adapts("distributed_lock", "lanes")
class DistributedLockLanes(LaneAdapter):
    """The jobs' view: jobs wait for the lock (the door: shut while it is stuck) in front of the storage
    (the server, its gauge the writes it accepts). A finished job is green, one that failed grey; a write
    from a lost lock lands red when the storage accepted it, orange when it refused it."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.distributed_lock import lab
        from live.worlds.distributed_lock import (
            JOB_END, JOB_ID, JOB_OK, JOB_START, SLOW_STALL, W_ACCEPTED, W_ARRIVED, W_JOB, corrupt, landed, refused,
            stall_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting = {}
        for r in run.active("jobs", t, JOB_END):
            waited = t - r[JOB_START]
            shade = (WHITE if waited < WAITED[0] else EXTRA1 if waited < WAITED[1] else EXTRA2
                     if waited < WAITED[2] else EXTRA3)
            waiting[slot(r[JOB_ID], users)] = (shade, True)
        flights = [(slot(r[JOB_ID], users), (t - r[JOB_START]) / FLY, WHITE, False)
                   for r in every(run.rows("jobs", t - FLY, t + 1e-9), FLIGHTS)]
        # Late writes from a lost lock fly in big, from their job's circle, as they land.
        late = [x for x in landed(run, t - FLY, t + 1e-9) if corrupt(x) or refused(x)]
        flights += [(slot(x[W_JOB], users), (t - x[W_ARRIVED]) / FLY, RED if corrupt(x) else EXTRA2, True)
                    for x in late]
        span = run.max_dur.get("jobs", 0.0)
        ended = [r for r in run.rows("jobs", t - BACK - span, t + 1e-9) if t - BACK <= r[JOB_END] <= t]
        bad = [x for x in landed(run, t - BACK, t + 1e-9) if corrupt(x) or refused(x)]
        outcomes = [(RED if corrupt(x) else EXTRA2, (t - x[W_ARRIVED]) / BACK) for x in bad[:OUTCOMES]]
        room = OUTCOMES - len(outcomes)  # the rare late writes first, then the jobs that ended
        outcomes += [(GREEN if r[JOB_OK] else DIM, (t - r[JOB_END]) / BACK) for r in every(ended, room)] if room else []

        stuck = stall_at(run, t)
        closed = stuck > SLOW_STALL
        door = RED if stuck > lab.STUCK_MAX else EXTRA2 if closed else None
        accepted = sum(1 for x in landed(run, t - 1, t + 1e-9) if x[W_ACCEPTED])
        recent = w.recent_writes(run, t)
        outline = RED if any(map(corrupt, recent)) else EXTRA2 if any(map(refused, recent)) else OUTLINE
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=closed, door_color=door,
                         fill=min(1.0, accepted / GAUGE_MAX), gauge=BLUE, outline=outline,
                         state=w.state_at(variant, t, short=True))
