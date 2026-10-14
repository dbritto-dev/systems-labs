"""The pictures for lab stream_windowing: lanes (phones send events through the processor's door; the
server is the windowed processor, its gauge the windows it keeps) and cluster (producers → the log's
partitions → the processor, with its window state, the dashboard and the side output)."""

from __future__ import annotations

from labs.stream_windowing import lab
from labs.stream_windowing.scenario import DROPPED, SIDE, UPDATED, WRONG
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, GREEN, MUTED, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.worlds.base import clock

SHOW = 0.6  # seconds a phone stays lit after its event arrived
PART_NODES = (0, 3, 6)  # the log's partitions: the left column of the 3x3 grid
PROC, SINK, STATE, SIDE_NODE = 1, 2, 4, 5  # the processor and dashboard on top; state, side output below


def _state(w, run, t: float) -> tuple[str, tuple[int, int, int]]:
    """The words and colour under the picture: the watermark and the windows kept."""
    wm = w.watermark(run, t)
    kept = w.kept(run, t)
    if wm is None:
        return w.s("state_none"), MUTED
    text = w.s("state", wm=clock(wm), n=kept, max=lab.STATE_MAX)
    got = w.recent(run, t)
    if got.get(DROPPED) or got.get(WRONG, 0) >= 3:
        return text, RED
    if kept > lab.STATE_MAX:
        return text, EXTRA2
    return text, GREEN


def _late_first(rows: list[tuple], late_col: int) -> list[tuple]:
    """Late events first, so a few among hundreds a second still show."""
    late = [r for r in rows if r[late_col] >= 0]
    room = FLIGHTS - min(len(late), FLIGHTS // 2)
    return every(late, FLIGHTS // 2) + every([r for r in rows if r[late_col] < 0], room)


@adapts("stream_windowing", "lanes")
class StreamWindowingLanes(LaneAdapter):
    """Phones on the left light up when their event arrives, coloured by how late it is; the door
    is the processor's watermark: solid red while it drops late events. The outcome fades at the
    door (green counted, blue counted in an update, purple side output, red dropped or counted in
    the wrong window). The gauge is the windows the processor keeps, against the limit."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.stream_windowing import E_AT, E_LATE, E_OUTCOME, E_SOURCE, lateness_colour, outcome_colour

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        lit = sorted(run.rows("events", t - SHOW, t + 1e-9), key=lambda e: e[E_LATE])
        found = {slot(e[E_SOURCE], users): (lateness_colour(e[E_LATE]), True) for e in lit}
        flying = _late_first(run.rows("events", t - FLY, t + 1e-9), E_LATE)
        flights = [(slot(e[E_SOURCE], users), (t - e[E_AT]) / FLY, lateness_colour(e[E_LATE]), e[E_LATE] >= 0)
                   for e in flying]
        ended = run.rows("events", t - BACK, t + 1e-9)
        rare = [e for e in ended if e[E_OUTCOME] in (UPDATED, SIDE, DROPPED, WRONG)]
        shown = every(rare, OUTCOMES // 2)
        shown += every([e for e in ended if e not in shown], OUTCOMES - len(shown))
        outcomes = [(outcome_colour(e[E_OUTCOME]), (t - e[E_AT]) / BACK) for e in shown]

        got = w.recent(run, t)
        closed = bool(got.get(DROPPED))
        door = (RED if closed else BLUE if got.get(UPDATED) else PURPLE if got.get(SIDE)
                else EXTRA2 if got.get(WRONG, 0) >= 3 else None)
        kept = w.kept(run, t)
        gauge = RED if kept > lab.STATE_MAX else EXTRA2 if kept == lab.STATE_MAX else BLUE
        outline = EXTRA2 if w.incident_at(variant, t) is not None else OUTLINE
        return LaneFrame(users=found, flights=flights, outcomes=outcomes, closed=closed, door_color=door,
                         fill=min(1.0, kept / lab.STATE_MAX), gauge=gauge, outline=outline,
                         state=_state(w, run, t))


@adapts("stream_windowing", "cluster")
class StreamWindowingCluster(ClusterAdapter):
    """The pipeline as nodes on a 3x3 grid: the log's three partitions down the left, the processor
    and the dashboard (the sink) across the top, the processor's window state and the side output
    below them. Producers send events to the partitions (white); events go on to the processor,
    coloured by how late they are; counts fly to the dashboard (green the first, blue an update),
    too-late events to the side output (purple). Dropped events die in red on their way in."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.stream_windowing import (
            E_AT, E_LATE, E_OUTCOME, E_PART, EM_FIRST, EM_T, ending, lateness_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        arriving = run.rows("events", t - FLY, t + 1e-9)
        flights = [(-1, PART_NODES[e[E_PART]], (t - e[E_AT]) / FLY, WHITE) for e in every(arriving, FLIGHTS // 2)]
        for e in _late_first(arriving, E_LATE):
            flights.append((PART_NODES[e[E_PART]], PROC, (t - e[E_AT]) / FLY, lateness_colour(e[E_LATE])))
        for m in every(run.rows("emits", t - 2 * FLY, t + 1e-9), OUTCOMES):
            flights.append((PROC, SINK, (t - m[EM_T]) / (2 * FLY), GREEN if m[EM_FIRST] else BLUE))
        side = [e for e in arriving if e[E_OUTCOME] == SIDE]
        flights += [(PROC, SIDE_NODE, (t - e[E_AT]) / FLY, PURPLE) for e in every(side, OUTCOMES)]
        drops = [(PART_NODES[e[E_PART]], PROC, (t - e[E_AT]) / BACK)
                 for e in run.rows("events", t - BACK, t + 1e-9) if e[E_OUTCOME] in (DROPPED, WRONG)]

        lag = w.lagging(variant, t)
        got = w.recent(run, t)
        kept = w.kept(run, t)
        nodes = [BLUE] * 7
        for p, node in enumerate(PART_NODES):
            nodes[node] = EXTRA2 if p == lag else BLUE
        nodes[PROC] = RED if got.get(DROPPED) or got.get(WRONG, 0) >= 3 else BLUE
        wrong = any(not win.exact(t) for s, win in ending(run, t - 40.0, t - 3.0) if win.due(s, t))
        nodes[SINK] = RED if wrong else BLUE
        nodes[STATE] = RED if kept > lab.STATE_MAX else EXTRA2 if kept == lab.STATE_MAX else BLUE
        recent_side = sum(1 for e in run.rows("events", t - 5.0, t + 1e-9) if e[E_OUTCOME] == SIDE)
        nodes[SIDE_NODE] = PURPLE if recent_side else MUTED
        return ClusterFrame(nodes=nodes, flights=flights, drops=every(drops, 30), state=_state(w, run, t))
