"""The World: everything the screen knows about a lab comes from these hooks.

A World holds one endless *run* per variant ("main", "reference", ...). A run
is one simulation that never restarts (`scenario.stream(variant, seed=...)`),
handed over a minute at a time. `append()` adds a minute to the run, keeps the
last few minutes of raw rows (so you can seek back), and keeps per-second
history and settled goal results forever.

Every hook takes `(variant, t)` and must only use data at or before `t`, so
the screen never shows what has not happened yet.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any, Callable

from dataclasses import replace
from types import ModuleType

from core.i18n import IncidentText, lab_text, screen_text
from live.canvas import BLUE, GREEN, MUTED, ORANGE, RED, RGB

PIECE = 60.0  # seconds per piece
KEEP = 300.0  # seconds of raw rows you can seek back through


@dataclass(frozen=True, slots=True)
class Stage:
    label: str
    story: str  # "Challenge: ..." or "Solved: ..."
    colour: RGB
    next: str  # the next step, e.g. "Stage 1: retry failed calls in Client"


@dataclass(frozen=True, slots=True)
class Table:
    """One table of rows: the time column it is sorted by, and its time columns
    (the first and last give a row's duration)."""

    sort: int
    times: tuple[int, ...]


@dataclass(slots=True)
class Tile:
    title: str
    value: str
    target: str
    state: str  # "ok", "warn", "bad" or "idle"
    history: list[tuple[float, str]]  # last 30 s: (value, state)


@dataclass(slots=True)
class Bar:
    label: str
    segments: list[tuple[float, RGB]]


@dataclass(slots=True)
class Traffic:
    tiles: list[Tile]
    bars: list[Bar]
    limit: float
    limit_label: str
    headline: str
    headline_colour: RGB = MUTED
    title: str = ""  # the toplist's title (default: "Calls" in the screen's language)
    subtitle: str = ""  # default: "per second, last 1 s"
    top: float | None = None  # the toplist's scale (default: from the limit and the bars)
    unit: str = "/s"  # after each toplist value; "" for counts


@dataclass(slots=True)
class Incident:
    index: int  # 0-based; shown as #index+1
    t0: float
    t1: float  # equal to t0 for an instant incident such as a flush
    kind: str = ""
    severity: float = 1.0
    cause: str = ""


@dataclass(frozen=True, slots=True)
class GoalSpec:
    """One goal judged per incident.

    `window(inc)` is the time span it looks at; `measure(run, inc, upto)`
    returns (value, text) using only rows at or before `upto`; `ok(value)`
    says whether it passed; `doomed(run, inc, upto)` is True once it can no
    longer pass whatever happens next (an early ALERT).
    """

    rule: str
    phase: str  # "before", "during" or "after"
    fix: str
    window: Callable[[Incident], tuple[float, float]]
    measure: Callable[[Any, Incident, float], tuple[float | None, str]]
    ok: Callable[[float | None], bool]
    doomed: Callable[[Any, Incident, float], bool] | None = None
    settle_extra: float = 0.0  # wait this long after the window for slow requests
    key: str = ""  # its words (rule, fix) come from the lab's catalog: text.GOALS[key]


@dataclass(frozen=True, slots=True)
class GoalRow:
    status: str  # "ok", "alert" or "wait"
    rule: str
    value: str
    phase: str


@dataclass(frozen=True, slots=True)
class Settled:
    ok: bool
    value: str
    settle: float
    alert_at: float


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    t: float
    verb: str  # the word shown, up to 6 letters: DOWN, SPIKE, ALERTA, VUELVE, ...
    text: str
    colour: RGB
    incident: int
    fix: str = ""
    kind: str = ""  # what it is, in any language: start, end, alert, ok, warn

    @property
    def start(self) -> bool:
        """An incident starting (its cause is shown in full)."""
        return self.kind == "start"


class Run:
    def __init__(self, variant: str, gen: int = 0) -> None:
        self.variant = variant
        self.gen = gen
        self.pieces = 0
        self.end = 0.0  # simulated up to here
        self.tables: dict[str, list[tuple]] = {}
        self.keys: dict[str, list[float]] = {}
        self.max_dur: dict[str, float] = {}
        self.hist: dict[str, list[float]] = {}
        self.incidents: list[Incident] = []
        self.settled: dict[int, list[Settled | None]] = {}
        self.timeline: list[TimelineEvent] = []
        self.data: dict[str, Any] = {}  # anything else a World wants to keep

    # ---- per-second history (forever)

    def add(self, name: str, t: float, n: float = 1.0) -> None:
        if t < 0:
            return
        s = int(t)
        h = self.hist.setdefault(name, [])
        if s >= len(h):
            h.extend([0.0] * (s + 1 - len(h)))
        h[s] += n

    def series(self, name: str, a: int, b: int) -> list[float]:
        """Values for seconds a..b-1 (zeros where nothing was recorded)."""
        h = self.hist.get(name, [])
        return [h[s] if 0 <= s < len(h) else 0.0 for s in range(a, b)]

    def total(self, name: str, t: float) -> float:
        """Sum of a history over whole seconds before t."""
        h = self.hist.get(name, [])
        return sum(h[: max(0, int(t))])

    # ---- raw rows (last KEEP seconds)

    @property
    def earliest(self) -> float:
        """The earliest time you can seek to."""
        return max(0.0, self.end - KEEP)

    def rows(self, table: str, a: float, b: float) -> list[tuple]:
        """Rows whose sort time is in [a, b)."""
        keys = self.keys.get(table, [])
        return self.tables.get(table, [])[bisect_left(keys, a): bisect_left(keys, b)]

    def count(self, table: str, a: float, b: float) -> int:
        keys = self.keys.get(table, [])
        return bisect_left(keys, b) - bisect_left(keys, a)

    def active(self, table: str, t: float, end_col: int) -> list[tuple]:
        """Rows that started at or before t and end after t."""
        a = t - self.max_dur.get(table, 0.0) - 1e-9
        keys = self.keys.get(table, [])
        rows = self.tables.get(table, [])
        return [r for r in rows[bisect_left(keys, a): bisect_right(keys, t)] if r[end_col] > t]


class World:
    """Base class. Subclasses fill in the class attributes and the hooks.

    Words come from the lab's catalog (labs/<lab>/text/<lang>.py) when it has one:
    TITLE, INCIDENT, STAGES, GOALS, LEGEND, VERBS, CAUSES and STRINGS. `self.text` is
    that catalog and `self.screen` the screen's (live/text/<lang>.py); `self.s(key, ...)`
    formats one of the lab's STRINGS.
    """

    id: str = ""
    title: str = ""
    files: tuple[str, ...] = ()  # files you edit, shown in the footer
    view: str = "lanes"  # the picture it opens with; any view with an adapter for this lab works
    stages: list[Stage] = []
    stage_colours: tuple[RGB, ...] = ()  # one per stage, with text.STAGES
    legend: list[tuple] = []  # (colour or [colours], name or text.LEGEND key[, glyph])
    incident_name: str = "Incident"
    incident_verbs: tuple[str, str] = ("DOWN", "UP")  # words, or text.VERBS keys
    tables: dict[str, Table] = {}
    goals: list[GoalSpec] = []

    def __init__(self, params: dict | None = None) -> None:
        self.params = dict(params or {})
        self.runs: dict[str, Run] = {}
        self.screen: ModuleType = screen_text()
        self.text: ModuleType | None = None
        try:
            self.text = lab_text(self.id)
        except ModuleNotFoundError:
            pass
        if self.text is not None:
            self._apply_text(self.text)
        if not self.files and self.id:
            from core.contract import ROOT, module_path

            self.files = (str(module_path(self.id, "main").relative_to(ROOT)),)

    def _apply_text(self, text: ModuleType) -> None:
        """Take every word from the lab's catalog."""
        self.title = text.TITLE
        self.incident_name = text.INCIDENT.name
        if hasattr(text, "STAGES"):
            self.stages = [Stage(s.label, s.story, colour, s.next)
                           for s, colour in zip(text.STAGES, self.stage_colours)]
        self.goals = [replace(g, rule=text.GOALS[g.key].rule, fix=text.GOALS[g.key].fix) if g.key else g
                      for g in self.goals]
        names = getattr(text, "LEGEND", {})
        self.legend = [(item[0], names.get(item[1], item[1]), *item[2:]) for item in type(self).legend]

    def s(self, key: str, /, **values: Any) -> str:
        """One of the lab's STRINGS, formatted: self.s("down", load=3.9)."""
        return self.text.STRINGS[key].format(**values) if self.text else key

    def word(self, key: str) -> str:
        """An event verb from the lab's VERBS (or the key itself)."""
        return getattr(self.text, "VERBS", {}).get(key, key) if self.text else key

    def cause(self, inc: "Incident") -> str:
        """The incident's cause in words (a trace holds only its key)."""
        return getattr(self.text, "CAUSES", {}).get(inc.cause, inc.cause) if self.text else inc.cause

    @property
    def incident_phrases(self) -> IncidentText:
        if self.text is not None:
            return self.text.INCIDENT
        name = self.incident_name.lower()
        return IncidentText(self.incident_name, f"the {name}", f"the next {name}")

    # ------------------------------------------------------------ runs

    def start(self, variant: str, gen: int = 0) -> Run:
        """Begin a fresh run for `variant` (replacing any old one)."""
        run = Run(variant, gen)
        self.runs[variant] = run
        return run

    def run(self, variant: str) -> Run:
        return self.runs[variant]

    def append(self, variant: str, piece: dict) -> None:
        """Add the next minute of the run."""
        run = self.runs[variant]
        tables = {name: piece["tables"].get(name, []) for name in self.tables}
        for name, spec in self.tables.items():
            self._merge(run, name, spec, tables[name])
        for t0, t1, kind, severity, cause in piece.get("incidents", []):
            inc = Incident(len(run.incidents), t0, t1, kind, severity, cause)
            run.incidents.append(inc)
            self._add_incident_events(run, inc)
        run.pieces += 1
        run.end = piece["end"]
        self.ingest(run, tables, piece)
        # Forget old raw rows; history and totals stay.
        cutoff = run.end - KEEP - PIECE
        for name in self.tables:
            i = bisect_left(run.keys[name], cutoff)
            if i:
                del run.tables[name][:i]
                del run.keys[name][:i]
        self._settle(run)

    def _merge(self, run: Run, name: str, spec: Table, new: list[tuple]) -> None:
        rows = run.tables.setdefault(name, [])
        keys = run.keys.setdefault(name, [])
        if new:
            # Rows from the end of the previous piece can run past its end.
            i = bisect_right(keys, new[0][spec.sort])
            if i < len(rows):
                tail = rows[i:] + new
                tail.sort(key=lambda r: r[spec.sort])
                del rows[i:], keys[i:]
                new = tail
            rows.extend(new)
            keys.extend(r[spec.sort] for r in new)
            if len(spec.times) >= 2:
                a, b = spec.times[0], spec.times[-1]
                longest = max((r[b] - r[a] for r in new if r[b] is not None), default=0.0)
                run.max_dur[name] = max(run.max_dur.get(name, 0.0), longest)

    # ------------------------------------------------------------ goals

    def _settle_time(self, g: GoalSpec, inc: Incident) -> float:
        return g.window(inc)[1] + g.settle_extra

    def _settle(self, run: Run) -> None:
        """Judge each goal once its window has closed in the data (cached forever)."""
        for inc in run.incidents:
            results = run.settled.setdefault(inc.index, [None] * len(self.goals))
            if all(r is not None for r in results):
                continue
            for k, g in enumerate(self.goals):
                settle = self._settle_time(g, inc)
                if results[k] is not None or settle > run.end - 1.0:
                    continue
                value, text = g.measure(run, inc, math.inf)
                ok = g.ok(value)
                alert_at = settle
                if not ok and g.doomed is not None:
                    a = g.window(inc)[0]
                    k2 = 0
                    while a + k2 * 0.25 < settle:
                        if g.doomed(run, inc, a + k2 * 0.25):
                            alert_at = a + k2 * 0.25
                            break
                        k2 += 1
                results[k] = r = Settled(ok, text, settle, alert_at)
                verbs = self.screen.VERBS
                if r.ok:
                    ev = TimelineEvent(r.settle, verbs["ok"], f"{g.rule}: {r.value}", GREEN, inc.index,
                                       kind="ok")
                else:
                    # What it showed when it alerted (an early alert's final value comes later).
                    shown = g.measure(run, inc, r.alert_at)[1] if r.alert_at < settle else r.value
                    ev = TimelineEvent(r.alert_at, verbs["alert"], f"{g.rule}: {shown}", RED, inc.index,
                                       g.fix, kind="alert")
                run.timeline.append(ev)
            warned = run.data.setdefault("warned", set())
            if inc.index not in warned and inc.t1 + 1.0 <= run.end:
                warned.add(inc.index)
                for t, text in self.warnings(run, inc):
                    run.timeline.append(TimelineEvent(t, self.screen.VERBS["warn"], text, ORANGE, inc.index,
                                                      kind="warn"))
        run.timeline.sort(key=_event_order)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        """The event verb (up to 6 letters) for an incident starting or ending, e.g. SPIKE."""
        return self.word(self.incident_verbs[0 if start else 1])

    def _add_incident_events(self, run: Run, inc: Incident) -> None:
        run.timeline.append(TimelineEvent(inc.t0, self.incident_verb(inc, True),
                                          self.incident_text(inc, start=True), RED, inc.index, kind="start"))
        if inc.t1 > inc.t0:
            run.timeline.append(TimelineEvent(inc.t1, self.incident_verb(inc, False),
                                              self.incident_text(inc, start=False), BLUE, inc.index, kind="end"))
        run.timeline.sort(key=_event_order)

    def current_incident(self, variant: str, t: float) -> Incident | None:
        """The latest incident that has started, else the first one coming."""
        run = self.runs.get(variant)
        if run is None or not run.incidents:
            return None
        started = [i for i in run.incidents if i.t0 <= t]
        return started[-1] if started else run.incidents[0]

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.incident_name, n=inc.index + 1)

    def goal_title(self, variant: str, t: float) -> str:
        inc = self.current_incident(variant, t)
        return self.incident_title(inc) if inc else self.incident_name

    def goal_lines(self, variant: str, t: float) -> list[GoalRow]:
        run = self.runs.get(variant)
        inc = self.current_incident(variant, t)
        phases = self.screen.PHASES
        if run is None or inc is None:
            return [GoalRow("wait", g.rule, "–", phases[g.phase]) for g in self.goals]
        # The panel asks several times for the same moment (once per layout it tries): answer from a memo, kept
        # in the run, for as long as the run, the moment and the language stay the same.
        key = (t, inc.index, run.pieces, len(run.settled), id(phases))
        memo = run.data.get("goal_lines")
        if memo is not None and memo[0] == key:
            return list(memo[1])
        final = run.settled.get(inc.index)
        rows = []
        for k, g in enumerate(self.goals):
            a, _ = g.window(inc)
            f = final[k] if final else None
            if f is not None and t >= f.settle:
                rows.append(GoalRow("ok" if f.ok else "alert", g.rule, f.value, phases[g.phase]))
                continue
            text = g.measure(run, inc, t)[1] if t > a else "–"
            if f is not None:
                alert = (not f.ok) and t >= f.alert_at
            else:
                alert = g.doomed is not None and t > a and g.doomed(run, inc, t)
            rows.append(GoalRow("alert" if alert else "wait", g.rule, text, phases[g.phase]))
        run.data["goal_lines"] = (key, rows)
        return list(rows)

    def next_check(self, variant: str, t: float) -> str:
        """What will be judged next, without giving away future times."""
        sc = self.screen
        inc = self.current_incident(variant, t)
        if inc is None:
            return sc.NEXT_FIRST_RUN
        phrases = self.incident_phrases
        rows = self.goal_lines(variant, t)
        pending = [(g, r) for g, r in zip(self.goals, rows) if r.status == "wait"]
        if not pending:
            return sc.NEXT_INCIDENT.format(incident=phrases.next)
        g, _ = pending[0]
        if g.phase == "before" and t < inc.t0:
            return sc.NEXT_AT_START.format(rule=g.rule, incident=phrases.the)
        if g.phase == "during" and inc.t0 <= t < inc.t1:
            return sc.NEXT_AT_END.format(rule=g.rule, incident=phrases.the)
        if t < max(inc.t0, inc.t1):
            return sc.NEXT_AFTER.format(rule=g.rule, incident=phrases.the)
        return f"{clock(self._settle_time(g, inc))} {g.rule}"

    def stage_index(self, variant: str) -> int | None:
        """Which stage main.py is at, judged from the first incident's results."""
        run = self.runs.get(variant)
        first = run.settled.get(0) if run else None
        if not first or any(r is None for r in first):
            return None
        return self.judge_stage(run, first)

    def stage(self, variant: str) -> Stage | None:
        i = self.stage_index(variant)
        return None if i is None else self.stages[i]

    def timeline(self, variant: str) -> list[TimelineEvent]:
        run = self.runs.get(variant)
        return run.timeline if run else []

    def bands(self, variant: str, t: float) -> list[tuple[float, float, RGB]]:
        """Shaded spans on the chart: incidents that have started, cut at t."""
        run = self.runs.get(variant)
        if run is None:
            return []
        out = []
        for inc in run.incidents:
            if inc.t0 <= t:
                out.append((inc.t0, min(max(inc.t1, inc.t0 + 1.0), t), self.band_colour))
        return out

    band_colour: RGB = (44, 22, 30)
    chart_top: float = 0.0  # the chart's scale at least (it grows to fit)

    # ------------------------------------------------------------ hooks to fill

    def ingest(self, run: Run, tables: dict[str, list[tuple]], piece: dict) -> None:
        """Add a piece's (already shifted) rows to the per-second history."""

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return 0

    def warnings(self, run: Run, inc: Incident) -> list[tuple[float, str]]:
        return []

    def incident_text(self, inc: Incident, start: bool) -> str:
        return self.screen.STARTED if start else self.screen.ENDED

    def traffic(self, variant: str, t: float) -> Traffic:
        raise NotImplementedError

    def user_stats(self, variant: str, t: float) -> list[tuple[str, str, RGB]]:
        return []

    def stacks(self, variant: str) -> list[tuple[RGB, list[float]]]:
        """Per-second chart stacks, bottom first: [(colour, values by second)]."""
        return []

    def chart_limit(self) -> tuple[float, str] | None:
        return None

    def legend_notes(self) -> list[str]:
        return []

    # ------------------------------------------------------------ helpers for the hooks

    def request_stats(self, run: Run, table: str, start: int, end: int, ok: int, t: float,
                      busy: int = 20) -> list[tuple[str, str, RGB]]:
        """The usual Users widget: served and failed so far, waiting now, p50/p99 of the last 5 s.

        `table` holds one row per user request; `start`, `end` and `ok` are its columns.
        """
        from live.canvas import EXTRA2, WHITE

        words = self.screen.STATS
        s = int(t)
        span = run.max_dur.get(table, 0.0)
        partial = [r for r in run.rows(table, s - span - 1, t) if s <= r[end] < t]
        served = run.total("served", t) + sum(1 for r in partial if r[ok])
        failed = run.total("failed", t) + sum(1 for r in partial if not r[ok])
        waiting = len(run.active(table, t, end))
        recent = [r[end] - r[start] for r in run.rows(table, t - 5 - span, t) if t - 5 <= r[end] < t]
        return [
            (words["served"], fmt_int(served), GREEN),
            (words["failed"], fmt_int(failed), RED if failed else MUTED),
            (words["waiting"], fmt_int(waiting), EXTRA2 if waiting > busy else WHITE),
            (words["p50"], fmt_ms(percentile(recent, 50)), WHITE),
            (words["p99"], fmt_ms(percentile(recent, 99)), WHITE),
        ]


def _event_order(e: TimelineEvent) -> tuple[float, int]:
    """Time order; at the same time, an incident starting or ending shows as the newest."""
    return e.t, 1 if e.kind in ("start", "end", "") else 0


def clock(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60}:{t % 60:02d}"


def fmt_int(n: float) -> str:
    return f"{int(round(n)):,}"


def fmt_ms(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    ms = seconds * 1000
    if ms < 1:
        return "<1ms"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{seconds:.1f}s"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, math.ceil(p / 100 * len(v)) - 1))
    return v[k]


def state_colour(state: str) -> RGB:
    from live.canvas import GREEN, MUTED, ORANGE, RED

    return {"ok": GREEN, "warn": ORANGE, "bad": RED}.get(state, MUTED)


def worst(states: list[str]) -> str:
    order = {"idle": 0, "ok": 1, "warn": 2, "bad": 3}
    return max(states, key=lambda s: order.get(s, 0)) if states else "idle"


def history(run: Run, t: float, fn: Callable[[int], tuple[float, str]], n: int = 30) -> list[tuple[float, str]]:
    """The last n whole seconds before t, as (value, state) from fn(second)."""
    end = int(t)
    return [fn(s) if s >= 0 else (0.0, "idle") for s in range(end - n, end)]
