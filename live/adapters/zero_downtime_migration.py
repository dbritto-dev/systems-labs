"""The pictures for lab zero_downtime_migration: lanes (users → the app fleet as the door → the database,
its load as the gauge) and cluster (the six app instances, old and new, the migration runner, the primary
and its replica)."""

from __future__ import annotations

from labs.zero_downtime_migration import lab
from labs.zero_downtime_migration.scenario import (
    ERROR, HAS_NEW, HAS_OLD, INSTANCES, NEW_COL, OK, OLD_COL, WRITE,
)
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

RUNNER, PRIMARY, REPLICA = INSTANCES, INSTANCES + 1, INSTANCES + 2  # the bottom row of the grid
LOAD_MAX = 0.60  # the gauge turns orange above the load a backfill should stop at (main.py's LOAD_MAX)


def _outcome(r) -> tuple[int, int, int]:
    return GREEN if r[4] == OK else RED if r[4] == ERROR else EXTRA3


def _cols_colour(cols: int):
    """A query by the columns it touched: the old one (white), the new one (blue), both (light orange)."""
    if cols & OLD_COL and cols & NEW_COL:
        return EXTRA1
    return BLUE if cols & NEW_COL else WHITE


def _ended(run, t: float, span: float) -> list[tuple]:
    longest = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", t - span - longest, t + 1e-9) if t - span <= r[2] <= t]


def _state(w, run, t: float, failing: int) -> tuple[str, tuple[int, int, int]]:
    """The words and colour under the database: which columns hold the name, and how far the copy is."""
    from live.worlds.zero_downtime_migration import S_COPIED, S_RUNNING, S_SHUNNED

    x = w.sample_at(run, t)
    old, new, bits = w.columns(run, t)
    if failing:
        return w.s("state_failing", n=failing), RED
    if bits & HAS_OLD and bits & HAS_NEW:
        text = w.s("state_both", pct=100 * (x[S_COPIED] if x else 0) / max(1, w.rows_n))
    elif bits & HAS_NEW:
        text = w.s("state_new", new=new)
    else:
        text = w.s("state_old", old=old)
    if x is not None and x[S_SHUNNED]:
        return text, EXTRA2
    if w.load_at(run, t) >= lab.LOAD_LIMIT:
        return text, EXTRA2
    return text, PURPLE if x is not None and x[S_RUNNING] else GREEN


@adapts("zero_downtime_migration", "lanes")
class ZeroDowntimeMigrationLanes(LaneAdapter):
    """Users wait for their name (orange once a write takes longer than 40 ms); requests fly to the door,
    which is the app fleet: orange while old and new instances run side by side, shut in red while
    requests fail on a column that is gone. Answers fade at the door: green, red (failed) or deep orange
    (a wrong name). The server is the database: its gauge is the load, its outline purple while the
    backfill copies rows."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.zero_downtime_migration import REQ_END, REQ_ID, REQ_KIND, REQ_START, S_NEW, S_OLD, S_RUNNING

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting = {}
        for r in run.active("requests", t, REQ_END):
            waiting[slot(r[REQ_ID], users)] = (EXTRA2 if t - r[REQ_START] > lab.P99_MAX else WHITE, True)
        flying = run.rows("requests", t - FLY, t + 1e-9)
        flights = [(slot(r[REQ_ID], users), (t - r[REQ_START]) / FLY, WHITE, r[REQ_KIND] == WRITE)
                   for r in every(flying, FLIGHTS)]
        ended = _ended(run, t, BACK)
        bad = every([r for r in ended if r[4] != OK], OUTCOMES)
        if len(bad) < OUTCOMES:  # failures and wrong names first: a few among hundreds still show
            bad += every([r for r in ended if r[4] == OK], OUTCOMES - len(bad))
        outcomes = [(_outcome(r), (t - r[REQ_END]) / BACK) for r in bad]

        failing = sum(1 for r in _ended(run, t, 1.0) if r[4] == ERROR)
        x = w.sample_at(run, t)
        mixed = x is not None and x[S_OLD] and x[S_NEW]
        load = w.load_at(run, t)
        gauge = RED if load >= lab.LOAD_LIMIT else EXTRA2 if load > LOAD_MAX else BLUE
        outline = PURPLE if x is not None and x[S_RUNNING] else OUTLINE
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, closed=failing > 0,
                         door_color=EXTRA2 if mixed and not failing else None, fill=load, gauge=gauge,
                         outline=outline, state=_state(w, run, t, failing))


@adapts("zero_downtime_migration", "cluster")
class ZeroDowntimeMigrationCluster(ClusterAdapter):
    """Six app instances on the top rows (white on the old release, blue on the new one, dim while they
    restart, red while their requests fail), and below them the migration runner, the primary and its
    replica. Requests fly from the clients to an instance, then on to the primary, coloured by the
    columns they touch (white old, blue new, light orange both: a dual write); failures die in red on
    the way. Purple dots fly from the runner while it copies rows; orange ones to the replica while it
    lags. The primary is coloured by its load; the replica turns orange when it lags and red when it is
    out of the pool."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.zero_downtime_migration import (
            REQ_COLS, REQ_END, REQ_INST, REQ_NEW, REQ_START, S_BASE, S_DOWN, S_LAG, S_NEW, S_OLD, S_RUNNING,
            S_SHUNNED, S_COPIED, S_BITS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        x = w.sample_at(run, t)
        recent = run.rows("requests", t - 2.0, t + 1e-9)
        # Which release each instance runs: the latest request it served says.
        new_at: dict[int, bool] = {}
        for r in recent:
            new_at[r[REQ_INST]] = r[REQ_NEW]
        failing = {r[REQ_INST] for r in _ended(run, t, 0.5) if r[4] == ERROR}
        served = {r[REQ_INST] for r in recent if r[REQ_START] >= t - 0.5}
        down = x[S_DOWN] if x else 0
        nodes = []
        for k in range(INSTANCES):
            if k in failing:
                nodes.append(RED)
            elif down and k not in served:
                nodes.append(DIM)  # restarting: no requests reach it
            else:
                nodes.append(BLUE if new_at.get(k) else WHITE)

        inc = w.incident_at(variant, t)
        ends = run.data.get("ends", {}).get(inc.index) if inc is not None else None
        if x is not None and x[S_RUNNING]:
            nodes.append(PURPLE)
        elif ends is not None and ends[0] <= t:
            nodes.append(GREEN if ends[1] == "done" else RED)
        else:
            nodes.append(WHITE if inc is not None else MUTED)
        load = w.load_at(run, t)
        nodes.append(RED if load >= lab.LOAD_LIMIT else EXTRA2 if load > LOAD_MAX else BLUE)
        lag = x[S_LAG] if x else 0.0
        nodes.append(RED if x is not None and x[S_SHUNNED] else EXTRA2 if lag > 0.5 else BLUE)

        flights = []
        for r in every(run.rows("requests", t - FLY, t + 1e-9), 2 * FLIGHTS):
            p = (t - r[REQ_START]) / FLY
            if p < 0.5:
                flights.append((-1, r[REQ_INST], 2 * p, WHITE))
            else:
                flights.append((r[REQ_INST], PRIMARY, 2 * p - 1, _cols_colour(r[REQ_COLS])))
        for r in every([r for r in run.active("requests", t, REQ_END) if r[REQ_START] < t - FLY], FLIGHTS):
            flights.append((r[REQ_INST], PRIMARY, 0.9, EXTRA2))  # still waiting: it sits by the database
        if x is not None and x[S_RUNNING]:
            flights += [(RUNNER, PRIMARY, (t * 2.0 + j / 3) % 1.0, PURPLE) for j in range(3)]
        if lag > 0.1:
            flights += [(PRIMARY, REPLICA, (t * 1.5 + j / 3) % 1.0, EXTRA2) for j in range(3)]
        drops = [(r[REQ_INST], PRIMARY, (t - r[REQ_END]) / BACK)
                 for r in every([r for r in _ended(run, t, BACK) if r[4] != OK], OUTCOMES)]

        failing_n = sum(1 for r in _ended(run, t, 1.0) if r[4] == ERROR)
        base = x[S_BASE] if x else 0
        text = w.s("cluster_state", va=base, na=x[S_OLD] if x else INSTANCES, vb=base + 1, nb=x[S_NEW] if x else 0,
                   lag=lag)
        if x is not None and x[S_BITS] & HAS_OLD and x[S_BITS] & HAS_NEW:
            text += w.s("cluster_copied", pct=100 * x[S_COPIED] / max(1, w.rows_n))
        _, colour = _state(w, run, t, failing_n)
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops, state=(text, colour))

