"""The pictures for lab async_backpressure: pipeline (events waiting upstream, the source as the door,
stages A, B, C and the sink in a row, each gauge what it holds), lanes (events, the pipeline's source
as the door, the process writing to the sink as the server, its memory as the gauge) and cluster
(source, stages A, B, C and the sink in one row, with what each holds)."""

from __future__ import annotations

from labs.async_backpressure import lab
from labs.async_backpressure.api import BASE_MEMORY, MAX_BATCH, MEMORY_LIMIT, READ_MAX, SIZE
from labs.async_backpressure.scenario import LOST, OOM, SHED, UPSTREAM, WRITTEN
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_pipeline import Leaf, PipelineAdapter, PipelineFrame

PAUSED = 4 * READ_MAX  # events waiting upstream: the source is not keeping up (the door shows it closed)


def _state(w, run, variant: str, t: float):
    """What the process is going through: (words, colour), and the last tick."""
    from live.worlds.async_backpressure import T_ALIVE, T_LUP, T_MEM, T_UP

    tick = w.tick_at(run, t)
    if tick is None:
        return (w.screen.STATES["healthy"], GREEN), None
    mem = tick[T_MEM] / MEMORY_LIMIT
    inc = w.incident_at(variant, t)
    s = int(t)
    if not tick[T_ALIVE]:
        state = (w.s("state_restarting"), RED)
    elif any(r[T_LUP] for r in run.rows("ticks", t - 1, t + 1e-9)):
        state = (w.s("state_lost"), RED)
    elif mem > lab.PEAK_MAX:
        state = (w.s("state_memory"), EXTRA2)
    elif run.series("shed", s - 1, s)[0]:
        state = (w.s("state_shed"), MUTED)
    elif tick[T_UP] > PAUSED:
        state = (w.s("state_paused"), EXTRA2)
    elif inc is not None:
        state = (w.s(f"state_{inc.kind}"), BLUE)
    else:
        state = (w.screen.STATES["healthy"], GREEN)
    return state, tick


def _outcomes(w, run, t: float) -> list:
    """Events' fates fading at the door: lost and shed first, so a few among many still show."""
    from live.worlds.async_backpressure import E_END, outcome_colour

    ended = w.ended(run, t - BACK, t + 1e-9)
    rare = [e for e in ended if outcome_colour(e) != GREEN]
    shown = every(rare, OUTCOMES)
    if len(shown) < OUTCOMES:
        shown += every([e for e in ended if outcome_colour(e) == GREEN], OUTCOMES - len(shown))
    return [(outcome_colour(e), (t - e[E_END]) / BACK) for e in shown]


@adapts("async_backpressure", "lanes")
class AsyncBackpressureLanes(LaneAdapter):
    """Each traced event (one in ten) is a user: it waits (white, then deeper orange the longer it has
    waited, upstream or in a queue) until the source reads it, flies to the door (the source), and its
    fate fades there: green written, grey shed (a LOW event, counted), red lost (the upstream's buffer
    overflowed, or the process was OOM-killed with it). The door is closed while the source is not
    keeping up (the upstream holds a backlog) and red while the process restarts. The server is the
    process; its gauge is its memory (orange above 80%)."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.async_backpressure import E_ARR, E_ID, E_READ, T_ALIVE, T_MEM, T_UP, wait_colour

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(e[E_ID], users): (wait_colour(t - e[E_ARR]), True) for e in w.pending(run, t)}
        read = [e for e in run.rows("events", t - FLY - 60.0, t + 1e-9)
                if e[E_READ] is not None and t - FLY <= e[E_READ] <= t]
        flights = [(slot(e[E_ID], users), (t - e[E_READ]) / FLY, wait_colour(e[E_READ] - e[E_ARR]), False)
                   for e in every(read, FLIGHTS)]
        state, tick = _state(w, run, variant, t)
        mem = 0.0 if tick is None else tick[T_MEM] / MEMORY_LIMIT
        down = tick is not None and not tick[T_ALIVE]
        paused = tick is not None and tick[T_UP] > PAUSED
        return LaneFrame(
            users=found, flights=flights, outcomes=_outcomes(w, run, t),
            closed=down or paused, door_color=RED if down else EXTRA2 if paused else None,
            fill=min(1.0, mem), gauge=RED if mem > 0.95 else EXTRA2 if mem > lab.PEAK_MAX else BLUE,
            outline=RED if down else EXTRA2 if mem > lab.PEAK_MAX else OUTLINE,
            state=(w.s("pic_mem", state=state[0], pct=f"{mem:.0%}"), state[1]),
        )


def _depth_colour(n: int):
    """A stage by how many events it holds: calm blue, then deeper orange."""
    return BLUE if n <= 200 else EXTRA1 if n <= 1000 else EXTRA2 if n <= 3000 else EXTRA3


@adapts("async_backpressure", "cluster")
class AsyncBackpressureCluster(ClusterAdapter):
    """The pipeline in one row: the source (node 0), stage A parse (1), stage B enrich (2), stage C
    write (3) and the sink (4); the firehose is the clients' column on the left.

    Each traced event flies along it as it moves: into the source when it arrives, on to A when it is
    read, to B when parsed, to C when enriched, into the sink (green) when written. A shed event flies
    back to the firehose in grey; a lost one fades red where it was (at the source when the upstream
    dropped it, inside the pipeline in an OOM kill). Under each node, what it holds: the source the
    events waiting upstream, A/B/C the events in their queue and in their hands, the sink how fast it
    writes (or DOWN, or how many times slower). A stage is blue while it holds little, deeper orange
    the more it holds; everything goes dim while the process restarts.
    """

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.async_backpressure import (
            E_ARR, E_END, E_ENR, E_OUT, E_PARSED, E_READ, E_WHERE, T_ALIVE, T_ENR, T_MEM, T_PARSED, T_RAW,
            T_UP, W_END, W_N, W_OK, compact,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        state, tick = _state(w, run, variant, t)
        up = 0 if tick is None else tick[T_UP]
        held = (0, 0, 0) if tick is None else (tick[T_RAW], tick[T_PARSED], tick[T_ENR])
        alive = tick is None or tick[T_ALIVE]
        inc = w.incident_at(variant, t)

        moves = []  # (time, from, to, colour)
        for e in run.rows("events", t - FLY - 60.0, t + 1e-9):
            if t - FLY <= e[E_ARR] <= t:
                moves.append((e[E_ARR], -1, 0, WHITE))
            for col, a in ((E_READ, 0), (E_PARSED, 1), (E_ENR, 2)):
                if e[col] is not None and t - FLY <= e[col] <= t:
                    moves.append((e[col], a, a + 1, WHITE))
            end = e[E_END]
            if end is not None and t - FLY <= end <= t:
                if e[E_OUT] == WRITTEN:
                    moves.append((end, 3, 4, GREEN))
                elif e[E_OUT] == SHED:
                    moves.append((end, 0, -1, MUTED))
        flights = [(a, b, (t - at) / FLY, colour) for at, a, b, colour in every(sorted(moves), FLIGHTS)]
        drops = []
        for e in every([e for e in w.ended(run, t - BACK, t + 1e-9) if e[E_OUT] == LOST], OUTCOMES):
            if e[E_WHERE] == UPSTREAM:
                where = (-1, 0)
            elif e[E_WHERE] == OOM:
                where = (1, 2) if e[E_PARSED] is None else (2, 3) if e[E_ENR] is None else (3, 4)
            else:
                where = (0, 1)
            drops.append((*where, (t - e[E_END]) / BACK))

        writes = [r for r in run.rows("writes", t - 3.0, t + 1e-9) if r[W_END] <= t]
        rate = sum(r[W_N] for r in writes if r[W_OK] and r[W_END] > t - 1.0)
        if inc is not None and inc.kind == "outage":
            sink, label = RED, w.s("lbl_down")
        elif inc is not None and inc.kind == "slow":
            sink, label = EXTRA2, w.s("lbl_slow", n=inc.severity)
        else:
            sink, label = BLUE, w.s("lbl_rate", n=compact(rate))
        source = RED if state[1] == RED and alive else EXTRA2 if up > PAUSED else BLUE
        stages = [_depth_colour(n) for n in held]
        if not alive:
            source, stages = DIM, [DIM] * 3
        nodes = [source, *stages, sink]
        labels = [(w.s("lbl_in", n=compact(up)), source if source != DIM else MUTED)]
        labels += [(w.s(key, n=compact(n)), MUTED if c == DIM else c)
                   for key, n, c in zip(("lbl_a", "lbl_b", "lbl_c"), held, stages)]
        labels.append((label, sink))
        mem = 0.0 if tick is None else tick[T_MEM] / MEMORY_LIMIT
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops, columns=len(nodes), labels=labels,
                            state=(w.s("pic_state", pct=f"{mem:.0%}", state=state[0]), state[1]))


@adapts("async_backpressure", "pipeline")
class AsyncBackpressurePipeline(PipelineAdapter):
    """The pipeline as it is: each traced event (one in ten) is a user while it waits upstream (white,
    then deeper orange the longer it waits); when the source reads it, it flies to the door (the source:
    closed while it is not keeping up, red while the process restarts after an OOM kill) and hops along
    the row: stage A parse, B enrich, C write, and into the sink (green). Each stage's gauge is what it
    holds, as a share of the memory there is for events (a full gauge is an OOM kill), its colour how
    many events that is; the sink's gauge is the batch it is writing. Every box's outline turns orange
    above 80% of the memory, red while the process is down; the sink's is red while it is down and
    orange while it is slow. A shed LOW event flies back to the door in grey and fades there; a lost one
    fades red there (the upstream dropped it) and, killed in an OOM, where it was in the row."""

    ROOM = MEMORY_LIMIT - BASE_MEMORY  # the bytes there are for events: a stage that holds them all is a kill

    def frame(self, variant: str, t: float, users: int) -> PipelineFrame:
        from live.worlds.async_backpressure import (
            E_ARR, E_END, E_ENR, E_ID, E_OUT, E_PARSED, E_READ, E_WHERE, T_ALIVE, T_ENR, T_MEM, T_PARSED,
            T_RAW, T_UP, W_END, W_N, W_OK, W_START, compact, wait_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PipelineFrame()
        upstream = [e for e in w.pending(run, t) if e[E_READ] is None or e[E_READ] > t]
        found = {slot(e[E_ID], users): (wait_colour(t - e[E_ARR]), True) for e in upstream}
        recent = run.rows("events", t - 2 * FLY - 60.0, t + 1e-9)
        read = [e for e in recent if e[E_READ] is not None and t - FLY <= e[E_READ] <= t]
        flights = [(slot(e[E_ID], users), (t - e[E_READ]) / FLY, wait_colour(e[E_READ] - e[E_ARR]), False)
                   for e in every(read, FLIGHTS)]
        moves = []  # (time, segment, colour, back): the door -> A when the flight reaches it, then on
        for e in recent:
            if e[E_READ] is not None and t - FLY <= e[E_READ] + FLY <= t:
                moves.append((e[E_READ] + FLY, 0, WHITE, False))
            for col, k in ((E_PARSED, 1), (E_ENR, 2)):
                if e[col] is not None and t - FLY <= e[col] <= t:
                    moves.append((e[col], k, WHITE, False))
            end = e[E_END]
            if end is not None and t - FLY <= end <= t:
                if e[E_OUT] == WRITTEN:
                    moves.append((end, 3, GREEN, False))
                elif e[E_OUT] == SHED:
                    moves.append((end, 0, MUTED, True))  # back to the door
        hops = [(k, (t - at) / FLY, colour, back) for at, k, colour, back in every(sorted(moves), FLIGHTS)]
        ended = w.ended(run, t - BACK, t + 1e-9)
        gone = [e for e in ended if e[E_OUT] in (SHED, LOST)]
        shown = every([e for e in gone if e[E_OUT] == LOST], OUTCOMES)
        shown += every([e for e in gone if e[E_OUT] == SHED], OUTCOMES - len(shown))
        outcomes = [(RED if e[E_OUT] == LOST else MUTED, (t - e[E_END]) / BACK) for e in shown]
        drops = []
        for e in every([e for e in ended if e[E_OUT] == LOST and e[E_WHERE] == OOM], OUTCOMES):
            k = 1 if e[E_PARSED] is None else 2 if e[E_ENR] is None else 3  # just after the stage it was in
            drops.append((k, (t - e[E_END]) / BACK))

        state, tick = _state(w, run, variant, t)
        mem = 0.0 if tick is None else tick[T_MEM] / MEMORY_LIMIT
        down = tick is not None and not tick[T_ALIVE]
        paused = tick is not None and tick[T_UP] > PAUSED
        high = mem > lab.PEAK_MAX
        outline = RED if down else EXTRA2 if high else OUTLINE
        held = (0, 0, 0) if tick is None else (tick[T_RAW], tick[T_PARSED], tick[T_ENR])
        boxes = []
        for k, (key, n) in enumerate(zip(("lbl_a", "lbl_b", "lbl_c"), held)):
            colour = DIM if down else _depth_colour(n)
            name = w.s(key, n=compact(n))
            boxes.append(Leaf((name, MUTED if down else colour), n * SIZE[k] / self.ROOM, colour, outline,
                              tiny=name.split()[0]))
        inc = w.incident_at(variant, t)
        writing = sum(r[W_N] for r in run.rows("writes", t - 5.0, t + 1e-9) if r[W_START] <= t < r[W_END])
        if inc is not None and inc.kind == "outage":
            sink, how = RED, w.s("lbl_down")
        elif inc is not None and inc.kind == "slow":
            sink, how = EXTRA2, w.s("lbl_slow", n=inc.severity)
        else:
            rate = sum(r[W_N] for r in run.rows("writes", t - 3.0, t + 1e-9) if r[W_OK] and t - 1.0 < r[W_END] <= t)
            sink, how = BLUE, w.s("lbl_rate", n=compact(rate))
        boxes.append(Leaf((w.s("lbl_sink", state=how), sink), writing / MAX_BATCH, BLUE,
                          RED if down or sink == RED else EXTRA2 if high or sink == EXTRA2 else OUTLINE,
                          short=how, tiny=w.s("lbl_sink_tiny")))
        return PipelineFrame(
            users=found, flights=flights, outcomes=outcomes,
            closed=down or paused, door_color=RED if down else EXTRA2 if paused else None,
            boxes=boxes, hops=hops, drops=drops,
            state=(w.s("pic_state", pct=f"{mem:.0%}", state=state[0]), state[1]),
        )
