"""The pictures for lab distributed_lock: cluster (the lock service, 4 workers and the storage, with the
lock's messages and the writes in flight) and lanes (jobs waiting for the lock, the door, in front of the
storage)."""

from __future__ import annotations

from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every, just_ended, just_sent, user_flights
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, EXTRA3, GREEN, PINK, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_fanin import FaninAdapter, FaninFrame, Leaf

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
    frozen worker is orange and its writes wait just outside it; a crashed one is red, a cut-off one pink. A write
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
            nodes[sick[0]] = {"pause": EXTRA2, "crash": RED}.get(sick[1], PINK)  # as in the fan-in picture
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
        flights = user_flights(every(just_sent(run, "jobs", t), FLIGHTS), t, JOB_START,
                               lambda r: (slot(r[JOB_ID], users), WHITE, False))
        # Late writes from a lost lock fly in big, from their job's circle, as they land.
        late = [x for x in landed(run, t - FLY, t + 1e-9) if corrupt(x) or refused(x)]
        flights += user_flights(late, t, W_ARRIVED,
                                lambda x: (slot(x[W_JOB], users), RED if corrupt(x) else EXTRA2, True))
        ended = just_ended(run, "jobs", JOB_END, t)
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


# ---------------------------------------------------------------- the fan-in picture: lock, workers, storage

TOKEN_KEEP = 0.95  # how far along its line a write stops while it is still in flight
LANDED = 1.5  # seconds a late write's burst stays at the storage (as long as the state says so)


@adapts("distributed_lock", "fanin")
class DistributedLockFanin(FaninAdapter):
    """Jobs wait (the users) for the lock service (the door: dotted while the lock is free, a solid bar
    while someone holds it, orange, then red, while it is stuck), which hands the lock to one of the
    workers w1..w4 (green while it holds it, orange while frozen, red when crashed, pink when cut off). Lock
    messages (acquire, renew, release and their answers) fly blue between the door and a worker. Every
    worker writes to the one storage (the store, its gauge the writes it accepts): writes fly white, light
    orange while one sits in the network, and wait just outside a frozen worker. A late write from a lost
    lock bursts red at the storage when it was accepted, orange when fencing refused it. The fencing token
    the lock handed out last is under the storage."""

    def frame(self, variant: str, t: float, users: int) -> FaninFrame:
        from labs.distributed_lock import lab
        from labs.distributed_lock.scenario import LOCK, LOCK_MSG, STORAGE, WORKERS, WRITE_REPLY
        from live.worlds.distributed_lock import (
            G_SEQ, JOB_END, JOB_WORKER, MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, SLOW_STALL,
            W_ARRIVED, W_LEFT, W_WORKER, corrupt, name, refused, stall_at,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FaninFrame()
        lane = DistributedLockLanes(w).frame(variant, t, users)  # the jobs waiting, and the storage's gauge
        leaf = {wk: j for j, wk in enumerate(WORKERS)}
        hops, joins = [], []
        for m in run.rows("msgs", t - DROP_FADE - 1, t + 1e-9):
            if m[MSG_ARRIVED] is None:
                continue
            p = _flight(t, m[MSG_SENT], m[MSG_ARRIVED])
            if p is None:
                continue
            src, dst, kind = m[MSG_SRC], m[MSG_DEST], m[MSG_KIND]
            if kind == LOCK_MSG and LOCK in (src, dst):
                other = dst if src == LOCK else src
                if other in leaf:
                    hops.append((leaf[other], p, BLUE, src != LOCK))  # worker → lock flies back along the line
            elif kind == WRITE_REPLY and src == STORAGE and dst in leaf:
                joins.append((leaf[dst], p, DIM, True))
        span = run.max_dur.get("writes", 0.0)
        for x in run.rows("writes", t - span - LANDED - 1e-9, t + 1e-9):
            j = leaf.get(x[W_WORKER])
            if j is None:
                continue
            if t < x[W_LEFT]:  # held by a frozen worker, just outside it
                joins.append((j, HELD, EXTRA2, False))
                continue
            p = _flight(t, x[W_LEFT], x[W_ARRIVED])
            if p is not None:
                late = x[W_ARRIVED] - x[W_LEFT] > 1.0  # it sits in the network
                joins.append((j, min(p, TOKEN_KEEP), EXTRA1 if late else WHITE, False))
            elif x[W_ARRIVED] <= t < x[W_ARRIVED] + LANDED and (corrupt(x) or refused(x)):
                colour = RED if corrupt(x) else EXTRA2
                joins += [(j, d, colour, False) for d in (0.86, 0.9, 0.94, 0.98)]  # a burst at the storage

        holder = w.holder_at(run, t)
        sick = w.sick_at(variant, t)
        busy = {r[JOB_WORKER] for r in run.active("jobs", t, JOB_END)}
        leaves = []
        for wk in WORKERS:
            node = name(wk)
            label, colour = (node, WHITE), OUTLINE
            # The colour says it (the legend): holds the lock green, frozen orange, dead red, cut off pink.
            if holder is not None and holder[1] == wk:
                label, colour = (node, GREEN), GREEN
            if sick is not None and sick[0] == wk and sick[1] != "delay":
                colour = {"pause": EXTRA2, "crash": RED}.get(sick[1], PINK)
                label = (node, colour)
            leaves.append(Leaf(label, short=node, fill=1.0 if wk in busy else 0.0, gauge=BLUE, outline=colour))

        stuck = stall_at(run, t)
        lock_colour = RED if stuck > lab.STUCK_MAX else EXTRA2 if stuck > SLOW_STALL else GREEN if holder else DIM
        grants = run.rows("grants", t - 120, t + 1e-9)
        text, colour = w.state_at(variant, t, short=True)
        if grants:
            text = w.s("fan_token", state=text, n=grants[-1][G_SEQ])
        who = w.s("nobody") if holder is None else name(holder[1])
        return FaninFrame(users=lane.users, flights=[f for f in lane.flights if not f[3]], outcomes=lane.outcomes,
                          closed=holder is not None, door_color=lock_colour, fill=lane.fill, gauge=lane.gauge,
                          outline=lane.outline, state=(text, colour), leaves=leaves, hops=hops,
                          joins=every(joins, MAX_FLIGHTS), door_label=(w.s("state_lock", worker=who), lock_colour))
