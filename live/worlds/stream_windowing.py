"""World for lab stream_windowing. Its words are in labs/stream_windowing/text/<lang>.py.

Every window is judged against the truth the lab keeps on the side: the events whose event time
falls in it. A window is exact when its latest count on the dashboard equals the events that
reached the processor before its allowed lateness ran out (by the lab's watermark: the largest
event time seen minus lab.DELAY). An event is dropped when it is neither in its window's count
nor in the side output.
"""

from __future__ import annotations

import math
from bisect import bisect_right

from labs.stream_windowing import lab
from labs.stream_windowing.scenario import (
    DROPPED, ON_TIME, SIDE, UPDATED, WRONG, lagging_partition,
)
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, MUTED, PURPLE, RED, RGB, WHITE,
)
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, clock, fmt_int, history, percentile,
)

DOWN_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
W = lab.WINDOW
KEEP_WINDOWS = 420.0  # seconds of windows (by event time) kept in the index

E_AT, E_ID, E_TIME, E_BORN, E_SOURCE, E_KIND, E_LATE, E_OUTCOME, E_PART = range(9)
EM_T, EM_START, EM_COUNT, EM_FIRST = range(4)
ST_T, ST_KEPT, ST_WM = range(3)


def window_of(t: float) -> float:
    return math.floor(t / W) * W


def lateness_colour(late: float) -> RGB:
    """An event's colour by how late it arrived: white on time, then deeper orange."""
    if late < 0:
        return WHITE
    if late < 10:
        return EXTRA1
    return EXTRA2 if late < lab.LATENESS else EXTRA3


def outcome_colour(outcome: int) -> RGB:
    return {ON_TIME: GREEN, UPDATED: BLUE, SIDE: PURPLE}.get(outcome, RED)


class Win:
    """One window's truth and results, in arrival order: what the goals need, as of any time."""

    __slots__ = ("at", "cin", "cside", "outs", "et", "ec")

    def __init__(self) -> None:
        self.at: list[float] = []  # arrival times of its events
        self.cin: list[int] = []  # running count of them within the allowed lateness
        self.cside: list[int] = []  # running count of them parked in the side output
        self.outs: list[int] = []  # each one's outcome
        self.et: list[float] = []  # times it was emitted
        self.ec: list[int] = []  # the count emitted each time

    def truth(self, upto: float) -> tuple[int, int, int]:
        """(events so far, of them within the lateness, of them in the side output)."""
        i = bisect_right(self.at, upto)
        return (i, self.cin[i - 1], self.cside[i - 1]) if i else (0, 0, 0)

    def final(self, upto: float) -> int | None:
        """Its latest count on the dashboard at `upto` (None: not emitted yet)."""
        j = bisect_right(self.et, upto)
        return self.ec[j - 1] if j else None

    def due(self, start: float, upto: float) -> bool:
        """Emitted by `upto`, or so old that it should have been."""
        return bool(self.et and self.et[0] <= upto) or upto >= start + W + lab.SETTLE

    def exact(self, upto: float) -> bool:
        return (self.final(upto) or 0) == self.truth(upto)[1]

    def missing(self, upto: float) -> int:
        """Events neither in its count nor in the side output (counted elsewhere, or dropped)."""
        n, _, side = self.truth(upto)
        return max(0, n - (self.final(upto) or 0) - side)


def wins(run: Run) -> dict[float, Win]:
    return run.data.setdefault("win", {})


def ending(run: Run, lo: float, hi: float) -> list[tuple[float, Win]]:
    """The windows that end in (lo, hi] and have seen an event or an emission."""
    index = wins(run)
    out = []
    end = window_of(lo) + W
    while end <= hi + 1e-9:
        if end > lo and (w := index.get(end - W)) is not None:
            out.append((end - W, w))
        end += W
    return out


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _span(inc: Incident) -> tuple[float, float]:
    """Windows an incident can change: late events up to the allowed lateness, and its own."""
    return inc.t0 - lab.LATENESS - W, inc.t1 + W


def _own(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + W


def _held(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + W + lab.SETTLE


def _share(rows: list[tuple[float, Win]], upto: float):
    due = [(s, w) for s, w in rows if w.due(s, upto)]
    if not due:
        return None, "–"
    v = sum(w.exact(upto) for _, w in due) / len(due)
    return v, f"{v:.0%}"


def _baseline(run: Run, inc: Incident, upto: float):
    """Events that arrived in the calm before the incident: the share counted in their own window."""
    a, b = _before(inc)
    rows = run.rows("events", a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(1 for e in rows if e[E_OUTCOME] in (ON_TIME, UPDATED)) / len(rows)
    return v, "100%" if v >= 1 else f"{math.floor(v * 1000) / 10:.1f}%"


def _final_by(inc: Incident) -> float:
    """When the windows an incident touched are final: later data belongs to later incidents."""
    return inc.t1 + W + lab.SETTLE


def _exact(run: Run, inc: Incident, upto: float):
    return _share(ending(run, *_span(inc)), min(upto, _final_by(inc)))


def _exact_doomed(run: Run, inc: Incident, upto: float) -> bool:
    """A window past its allowed lateness is wrong: nothing will fix it now."""
    upto = min(upto, _final_by(inc))
    return any(upto >= s + W + lab.SETTLE and not w.exact(upto) for s, w in ending(run, *_span(inc)))


def touched(run: Run, inc: Incident) -> dict[float, float]:
    """Windows that got an event arriving during the incident (or its tail): start -> first arrival."""
    return run.data.setdefault("touched", {}).setdefault(inc.index, {})


def _dropped_n(run: Run, inc: Incident, upto: float) -> int | None:
    upto = min(upto, _final_by(inc))
    index = wins(run)
    rows = dict(ending(run, *_span(inc)))
    for s, first in touched(run, inc).items():
        if first <= upto and s in index:
            rows[s] = index[s]
    due = [w for s, w in rows.items() if w.due(s, upto)]
    return sum(w.missing(upto) for w in due) if due else None


def _dropped(run: Run, inc: Incident, upto: float):
    n = _dropped_n(run, inc, upto)
    return (None, "–") if n is None else (n, fmt_int(n))


def _dropped_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return (_dropped_n(run, inc, upto) or 0) > lab.DROPPED_MAX


def first_result(s: float, w: Win, upto: float) -> float | None:
    """Seconds from the window's end to its first count (or to `upto`, if it is late and not there)."""
    end = s + W
    if w.et and w.et[0] <= upto:
        return max(0.0, w.et[0] - end)
    return upto - end if upto - end > lab.LATENCY_MAX else None


def _latencies(run: Run, inc: Incident, upto: float) -> list[float]:
    a, b = _own(inc)
    last = min(upto, run.end)
    return [v for s, w in ending(run, a - 1e-6, b) if (v := first_result(s, w, last)) is not None]


def _latency(run: Run, inc: Incident, upto: float):
    v = percentile(_latencies(run, inc, upto), 99)
    return (None, "–") if v is None else (v, f"{v:.1f}s")


def _latency_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return any(v > lab.LATENCY_MAX for v in _latencies(run, inc, upto))


def _state_max(run: Run, inc: Incident, upto: float) -> int | None:
    a, b = _held(inc)
    rows = run.rows("state", a, min(b, upto))
    return max((r[ST_KEPT] for r in rows), default=None)


def _state(run: Run, inc: Incident, upto: float):
    v = _state_max(run, inc, upto)
    return (None, "–") if v is None else (v, str(v))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, lambda v: v is not None and v >= lab.BASELINE_MIN,
             key="baseline"),
    GoalSpec("", "after", "", _span, _exact, lambda v: v is not None and v >= lab.EXACT_MIN,
             doomed=_exact_doomed, settle_extra=lab.SETTLE, key="exact"),
    GoalSpec("", "after", "", _own, _dropped, lambda v: v is not None and v <= lab.DROPPED_MAX,
             doomed=_dropped_doomed, settle_extra=lab.SETTLE, key="dropped"),
    GoalSpec("", "during", "", _own, _latency, lambda v: v is not None and v <= lab.LATENCY_MAX,
             doomed=_latency_doomed, settle_extra=lab.LATENCY_MAX + 1.0, key="latency"),
    GoalSpec("", "during", "", _held, _state, lambda v: v is not None and v <= lab.STATE_MAX,
             doomed=lambda run, inc, upto: (_state_max(run, inc, upto) or 0) > lab.STATE_MAX,
             settle_extra=1.0, key="state"),
]


class StreamWindowingWorld(World):
    id = "stream_windowing"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "on_time"), ([EXTRA1, EXTRA2, EXTRA3], "late"),
              (GREEN, "counted"), (BLUE, "updated"), (PURPLE, "side"), (RED, "dropped"),
              (DOWN_KEY, "incident", "█")]
    tables = {
        "events": Table(sort=E_AT, times=(E_AT,)),
        "emits": Table(sort=EM_T, times=(EM_T,)),
        "state": Table(sort=ST_T, times=(ST_T,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 40.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        index = wins(run)
        live = run.incidents[-3:]
        for e in tables["events"]:
            s = window_of(e[E_TIME])
            w = index.get(s)
            if w is None:
                w = index[s] = Win()
            inside = 1 if e[E_LATE] < lab.LATENESS else 0
            side = 1 if e[E_OUTCOME] == SIDE else 0
            w.at.append(e[E_AT])
            w.cin.append((w.cin[-1] if w.cin else 0) + inside)
            w.cside.append((w.cside[-1] if w.cside else 0) + side)
            w.outs.append(e[E_OUTCOME])
            for inc in live:
                if inc.t0 <= e[E_AT] < inc.t1 + lab.TAIL:
                    touched(run, inc).setdefault(s, e[E_AT])
            outcome = e[E_OUTCOME]
            run.add({ON_TIME: "on_time", UPDATED: "updated", SIDE: "side"}.get(outcome, "lost"), e[E_AT])
            if outcome == WRONG:
                run.add("wrong", e[E_AT])
        for m in tables["emits"]:
            w = index.get(m[EM_START])
            if w is None:
                w = index[m[EM_START]] = Win()
            w.et.append(m[EM_T])
            w.ec.append(m[EM_COUNT])
            if not m[EM_FIRST]:
                run.add("updates", m[EM_T])
        for s in [s for s in index if s < run.end - KEEP_WINDOWS]:
            del index[s]

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        rows = run.rows("events", inc.t0, inc.t1 + 1.0)
        out = []
        dropped = sum(1 for e in rows if e[E_OUTCOME] == DROPPED)
        if dropped:
            out.append((inc.t1, self.s("warn_dropped", n=dropped)))
        wrong = sum(1 for e in rows if e[E_OUTCOME] == WRONG)
        if wrong:
            out.append((inc.t1, self.s("warn_wrong", n=wrong)))
        return out

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", seconds=inc.severity, minutes=inc.severity / 60,
                      partition=lagging_partition(inc.t0), cause=self.cause(inc))

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    # ---------------------------------------------------------------- the processor at t

    def state_at(self, run: Run, t: float) -> tuple | None:
        """The latest sample of the processor's state at or before t."""
        rows = run.rows("state", t - 2.0, t + 1e-9)
        return rows[-1] if rows else None

    def kept(self, run: Run, t: float) -> int:
        st = self.state_at(run, t)
        return st[ST_KEPT] if st else 0

    def watermark(self, run: Run, t: float) -> float | None:
        st = self.state_at(run, t)
        return st[ST_WM] if st and st[ST_WM] > -1e300 else None

    def recent(self, run: Run, t: float, span: float = 1.0) -> dict[int, int]:
        """Events that arrived in the last `span` seconds, by outcome."""
        out: dict[int, int] = {}
        for e in run.rows("events", t - span, t + 1e-9):
            out[e[E_OUTCOME]] = out.get(e[E_OUTCOME], 0) + 1
        return out

    def lagging(self, variant: str, t: float) -> int | None:
        inc = self.incident_at(variant, t)
        return lagging_partition(inc.t0) if inc is not None and inc.kind == "lag" else None

    def window_label(self, s: float) -> str:
        end = int(s + W)
        return f"{clock(s)}–:{end % 60:02d}"

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        def exact_at(u: float):
            return _share(ending(run, u - 60.0, u - 3.0), u)[0]

        def exact_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.EXACT_MIN else "ok"

        def exact_s(s: int):
            v = exact_at(s + 1.0)
            return (1.0, "idle") if v is None else (v, exact_state(v))

        exact = exact_at(t)
        lost = sum(run.series("lost", int(t) - 30, int(t)))

        def lost_s(s: int):
            v = run.series("lost", s, s + 1)[0]
            return v, "bad" if v else "ok"

        def first_at(u: float) -> float | None:
            vals = [v for s, w in ending(run, u - 30.0, u) if (v := first_result(s, w, u)) is not None]
            return max(vals) if vals else None

        def lat_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.LATENCY_MAX else "warn" if v > 3.0 else "ok"

        def lat_s(s: int):
            v = first_at(s + 1.0)
            return min(v or 0.0, 10.0), lat_state(v)

        lat = first_at(t)
        tiles = [
            Tile(self.s("tile_exact"), "–" if exact is None else f"{exact:.0%}", "≥99%", exact_state(exact),
                 history(run, t, exact_s)),
            Tile(self.s("tile_dropped"), fmt_int(lost), "=0", "bad" if lost else "ok", history(run, t, lost_s)),
            Tile(self.s("tile_latency"), "–" if lat is None else f"{lat:.1f}s", "≤5s", lat_state(lat),
                 history(run, t, lat_s)),
        ]
        index = wins(run)
        bars = []
        top = window_of(t)
        shown = [s for s in (top - k * W for k in range(4, -1, -1))
                 if s >= 0 and (w := index.get(s)) is not None and w.at and w.at[0] <= t][-4:]
        for s in shown:
            w = index[s]
            counts = {o: 0 for o in (ON_TIME, UPDATED, SIDE, WRONG, DROPPED)}
            for o in w.outs[:bisect_right(w.at, t)]:
                counts[o] += 1
            bars.append(Bar(self.window_label(s), [
                (float(counts[ON_TIME]), WHITE), (float(counts[UPDATED]), BLUE), (float(counts[SIDE]), PURPLE),
                (float(counts[WRONG] + counts[DROPPED]), RED)]))
        headline, colour = self._headline(variant, run, t)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("bars"), subtitle=self.s("bars_sub"),
                       top=self.rate * W * 1.5, unit="")

    def _headline(self, variant: str, run: Run, t: float):
        got = self.recent(run, t, 2.0)
        if got.get(DROPPED):
            return self.s("head_dropped"), RED
        if got.get(WRONG, 0) >= 5:
            return self.s("head_wrong"), RED
        if got.get(SIDE):
            return self.s("head_side"), PURPLE
        if got.get(UPDATED):
            return self.s("head_updated"), BLUE
        if self.kept(run, t) > lab.STATE_MAX:
            return self.s("head_state"), EXTRA2
        inc = self.incident_at(variant, t)
        if inc is not None:
            return self.s(f"head_{inc.kind}"), EXTRA2
        if got.get(WRONG):
            return self.s("head_edges"), EXTRA2
        return self.s("head_calm"), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        partial = self.recent(run, t, t - s) if t > s else {}

        def total(name: str, *outcomes: int) -> float:
            return run.total(name, t) + sum(partial.get(o, 0) for o in outcomes)

        counted = total("on_time", ON_TIME) + total("updated", UPDATED)
        side = total("side", SIDE)
        lost = total("lost", WRONG, DROPPED)
        late = [e[E_AT] - e[E_TIME] for e in run.rows("events", t - 5.0, t)]
        p99 = percentile(late, 99)
        return [
            (self.s("stat_counted"), fmt_int(counted), GREEN),
            (self.s("stat_updates"), fmt_int(run.total("updates", t)), BLUE),
            (self.s("stat_side"), fmt_int(side), PURPLE if side else MUTED),
            (self.s("stat_dropped"), fmt_int(lost), RED if lost else MUTED),
            (self.s("stat_late"), "–" if p99 is None else f"{p99:.1f}s", EXTRA2 if p99 and p99 > 2 else WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("on_time", [])), (BLUE, run.hist.get("updated", [])),
                (PURPLE, run.hist.get("side", [])), (RED, run.hist.get("lost", []))]

    chart_top = 80.0

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = StreamWindowingWorld
