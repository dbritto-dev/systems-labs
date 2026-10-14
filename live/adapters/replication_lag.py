"""The pictures for lab replication_lag: the primary (top left) and replicas r1..r4, and the clients' view."""

from __future__ import annotations

from live.adapters.common import client_lanes, every
from live.canvas import BLUE, EXTRA2, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

DROP_FADE = 0.6  # seconds a wrong read stays on screen
READ_SHOWN = 0.12  # a read dot flies for ~100 ms (slowed down: a real read takes a few ms)
WRITE_SHOWN = 30.0  # replication still on its way can be this old (a restarted replica's backlog)
MAX_FLIGHTS = 90


@adapts("replication_lag", "cluster")
class ReplicationLagCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.replication_lag import (
            READ_MONO, READ_NODE, READ_OK, READ_RYW, READ_START, WRITE_LSN, WRITE_T,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for row in run.rows("writes", t - WRITE_SHOWN, t + 1e-9):  # the primary sends each write on
            for i, delay in enumerate(row[WRITE_LSN + 1:]):
                if t < row[WRITE_T] + delay:
                    flights.append((0, i + 1, (t - row[WRITE_T]) / delay, BLUE))
        for r in run.rows("reads", t - DROP_FADE, t + 1e-9):
            if not r[READ_OK] or r[READ_RYW] or r[READ_MONO]:
                drops.append((-1, r[READ_NODE], (t - r[READ_START]) / DROP_FADE))
            elif t - r[READ_START] < READ_SHOWN:
                flights.append((-1, r[READ_NODE], min(1.0, (t - r[READ_START]) / 0.1), WHITE))
        return ClusterFrame(nodes=w.node_colours(run, t), flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=w.state_at(variant, t))


# ---------------------------------------------------------------- the lanes picture: the clients' view

STALE_SHOWN = 1.0  # seconds a wrong read keeps the state red


@adapts("replication_lag", "lanes")
class ReplicationLagLanes(LaneAdapter):
    """The clients' view: reads through the router (the door, coloured by the worst replica) to the
    database; the server's gauge is the primary's share of the reads. An answer is green from a fresh
    replica, orange from the primary, red when it was stale (an own write not seen, or time going back)."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.replication_lag import lab, scenario
        from live.worlds.replication_lag import (
            READ_END, READ_MONO, READ_NODE, READ_OK, READ_RYW, READ_START, _behind_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def stale(r) -> bool:
            return not r[READ_OK] or r[READ_RYW] or r[READ_MONO]

        def colour(r):
            return RED if stale(r) else EXTRA2 if r[READ_NODE] == 0 else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "reads", READ_START, READ_END, colour=colour,
                                                   rare_first=True)
        last = [r for r in run.rows("reads", t - STALE_SHOWN, t + 1e-9) if r[READ_END] <= t]
        wrong = any(stale(r) for r in last)
        share = sum(1 for r in last if r[READ_NODE] == 0) / len(last) if last else 0.0
        lags, ups = w.lag_at(run, t)
        door = RED if not all(ups) else None if max(lags) < 0.5 else _behind_colour(max(lags))
        inc = w.incident_at(variant, t)
        words = w.screen.STATES
        if wrong:
            state = (w.s("lanes_stale"), RED)
        elif share > lab.PRIMARY_MAX:
            state = (w.s("lanes_primary", share=share), EXTRA2)
        elif inc is not None and not all(ups):
            state = (f"{scenario.NAMES_OF[ups.index(False) + 1]}  {words['down']}", RED)
        elif inc is not None:
            state = (w.s("lanes_lag", lag=min(99.9, max(lags))), EXTRA2)
        else:
            state = (words["healthy"], GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=door,
                         fill=share, gauge=EXTRA2 if share > lab.PRIMARY_MAX else BLUE,
                         outline=RED if wrong else OUTLINE, state=state)
