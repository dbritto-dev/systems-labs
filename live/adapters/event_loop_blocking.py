"""The pictures for lab event_loop_blocking: lanes (users → the process's socket as the door → the event loop
as the server, its gauge how busy the loop was) and cluster (the event loop as the first node, then every
worker of every pool: a thread or a process, coloured by the work it does)."""

from __future__ import annotations

from labs.event_loop_blocking import lab
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, client_lanes, every, just_ended, just_sent
from live.canvas import BLUE, EXTRA2, GREEN, RED, RGB, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.worlds.base import fmt_ms

THREAD_IDLE: RGB = (40, 46, 56)  # a thread with nothing to do
PROC_IDLE: RGB = (58, 46, 78)  # a process with nothing to do
DEAD: RGB = (60, 30, 34)  # the loop of a killed process
MAX_NODES = 49  # the loop and at most 48 workers (a 7x7 grid)
CPU_NAMES = ("resize", "report")


def _loop(w, run, t: float) -> tuple[str, RGB, bool]:
    """The loop at t: (its state with its lag, its colour, blocked or down: no lag to show)."""
    from live.worlds.event_loop_blocking import BLK_T0

    words = w.screen.STATES
    if w.down_at(run, t):
        return words["down"], RED, True
    stall = w.stall_at(run, t)
    if stall is not None and t - stall[BLK_T0] >= lab.LAG_MAX:
        return w.s("blocked", ms=(t - stall[BLK_T0]) * 1000), RED, True
    lag = w.lag_now(run, t, 0.5) or 0.0
    word, colour = ((words["degraded"], RED) if lag >= lab.LAG_MAX
                    else (words["busy"], EXTRA2) if lag >= lab.LAG_MAX / 2 else (words["healthy"], GREEN))
    return w.s("lane_state", state=word, lag=fmt_ms(lag)), colour, False


def _outcome_colour(r: tuple) -> RGB:
    from live.worlds.event_loop_blocking import REQ_OK, REQ_OUT, SHED, SHED_C

    return GREEN if r[REQ_OK] else SHED_C if r[REQ_OUT] == SHED else RED


@adapts("event_loop_blocking", "lanes")
class EventLoopLanes(LaneAdapter):
    """Users wait for an answer (orange the longer they wait); requests fly to the door, the process's socket
    (shut in red while the process is killed and restarting). The server is the event loop: its gauge is how
    much of the last second the loop was held (coloured by what held it most: blocking I/O, CPU, the GIL, a
    GC pause), its outline red while the loop runs late. Under it: its state and lag (BLOCKED counts up
    during a stall), or the calls queued in the executors when there are too many."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.event_loop_blocking import (
            CAUSE_COLOURS, CPU_COL, GC, GIL, IO, OWN, REQ_END, REQ_START, S_WAITING,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, flights, outcomes = client_lanes(run, t, users, "requests", REQ_START, REQ_END,
                                                  colour=_outcome_colour, rare_first=True)
        text, colour, stopped = _loop(w, run, t)
        down = w.down_at(run, t) is not None
        s = int(t) - 1
        busy = {col: run.series(f"busy{col}", s, s + 1)[0] for col in (OWN, IO, CPU_COL, GIL, GC)}
        fill = 1.0 if stopped else min(1.0, sum(busy.values()))
        gauge = CAUSE_COLOURS[max(busy, key=busy.get)] if fill >= 0.3 else BLUE
        sample = w.sample_at(run, t)
        if not stopped and sample is not None and sample[S_WAITING] > lab.QUEUED_MAX:
            text, colour = w.s("lane_busy", state=w.screen.STATES["busy"], n=sample[S_WAITING]), EXTRA2
        return LaneFrame(
            users=waiting, flights=flights, outcomes=outcomes, closed=down,
            fill=0.0 if down else fill, gauge=gauge, outline=RED if colour == RED else OUTLINE,
            state=(text, colour),
        )


def _workers(sample: tuple | None) -> list[tuple[int, int, bool]]:
    """(pool, worker, process) for every worker shown, in order: at most MAX_NODES - 1."""
    from live.worlds.event_loop_blocking import P_PROCESS, P_WORKERS, S_POOLS

    out: list[tuple[int, int, bool]] = []
    for p, pool in enumerate(sample[S_POOLS] if sample is not None else ()):
        for k in range(pool[P_WORKERS]):
            if len(out) >= MAX_NODES - 1:
                return out
            out.append((p, k, pool[P_PROCESS]))
    return out


@adapts("event_loop_blocking", "cluster")
class EventLoopCluster(ClusterAdapter):
    """The event loop is the first node (green, orange when late, red while blocked, dark when killed);
    every worker of every pool follows: a thread or a process, dim while idle, teal on blocking I/O, orange
    on CPU work, pink while it holds a call but waits for the GIL (a thread) or for a core (a process).
    Requests fly from the users to the loop, and calls from the loop to the worker that runs them; 503s and
    failures die in red on the way to the loop. Under it: the loop's state and lag, and each pool's
    busy/size +queued."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.event_loop_blocking import (
            CALL_END, CALL_NAME, CALL_POOL, CALL_RAN, CALL_START, CALL_WORKER, CPU_C, GIL_C, IO_C, P_DEFAULT,
            P_PROCESS, P_RUNNING, P_WAITING, P_WORKERS, REQ_END, REQ_OK, REQ_START, S_POOLS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        down = w.down_at(run, t) is not None
        sample = None if down else w.sample_at(run, t)
        workers = _workers(sample)
        index = {(p, k): i + 1 for i, (p, k, _) in enumerate(workers)}
        text, colour, _ = _loop(w, run, t)
        nodes = [DEAD if down else colour] + [PROC_IDLE if proc else THREAD_IDLE for _, _, proc in workers]
        span = run.max_dur.get("calls", 0.0)
        for c in run.rows("calls", t - span - 1e-9, t + 1e-9):
            i = index.get((c[CALL_POOL], c[CALL_WORKER]))
            if i is not None and c[CALL_START] <= t < c[CALL_END]:
                # Holding a call but waiting for the GIL (a thread) or a core (a process), or running it.
                nodes[i] = GIL_C if t < c[CALL_RAN] else CPU_C if c[CALL_NAME] in CPU_NAMES else IO_C
        flying = just_sent(run, "requests", t)
        flights = [(-1, 0, (t - r[REQ_START]) / FLY, WHITE) for r in every(flying, FLIGHTS)]
        sent = [c for c in just_sent(run, "calls", t) if (c[CALL_POOL], c[CALL_WORKER]) in index]
        flights += [(0, index[(c[CALL_POOL], c[CALL_WORKER])], (t - c[CALL_START]) / FLY,
                     CPU_C if c[CALL_NAME] in CPU_NAMES else IO_C) for c in every(sent, FLIGHTS)]
        span = run.max_dur.get("requests", 0.0)
        failed = [r for r in just_ended(run, "requests", REQ_END, t) if not r[REQ_OK]]
        drops = [(-1, 0, (t - r[REQ_END]) / BACK) for r in every(failed, OUTCOMES)]
        if down:
            text = w.s("cluster_down", state=text)
        else:
            parts = []
            for pool in sample[S_POOLS] if sample is not None else ():
                key = "pool_procs" if pool[P_PROCESS] else "pool_default" if pool[P_DEFAULT] else "pool_threads"
                parts.append(w.s(key, busy=pool[P_RUNNING], n=pool[P_WORKERS], q=pool[P_WAITING]))
            text = w.s("cluster_state", state=text, pools=" · ".join(parts) or w.s("no_pools"))
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops, state=(text, colour))
