"""World for lab zero_downtime_migration. Its words are in labs/zero_downtime_migration/text/<lang>.py."""

from __future__ import annotations

from labs.zero_downtime_migration import lab
from core.i18n import strings
from labs.zero_downtime_migration.scenario import (
    ERROR, HAS_NEW, HAS_OLD, NEW_COL, OK, OLD_COL, READS_NEW, SAMPLE, SHUN, WRITE, WRONG, rename,
)
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, IDLE_DOT, MUTED, PURPLE, RED, RGB, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, TimelineEvent, Traffic, World, _event_order,
    fmt_int, fmt_ms, history, percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_KIND, REQ_OUTCOME, REQ_INST, REQ_NEW, REQ_COLS = range(8)
(S_T, S_FIELD, S_TRAFFIC, S_OTHER, S_BF, S_LAG, S_SHUNNED, S_OLD, S_NEW, S_DOWN, S_BITS, S_COPIED, S_WRONG,
 S_RUNNING, S_TROUBLE, S_BASE) = range(16)
ST_T, ST_KEY, ST_WINDOW, ST_DETAIL = range(4)
W_T1, W_INDEX, W_T0, W_DONE, W_WRONG, W_OLD, W_NEW = range(7)

BACKFILL_KEY: RGB = (60, 44, 104)  # the chart's shading while copies run
TROUBLE_KEY: RGB = (110, 44, 56)  # ... and while the replica lags or the database is busy
_s = strings("zero_downtime_migration")
TROUBLE_BAND: RGB = (44, 22, 30)
BACKFILL_BAND: RGB = (30, 24, 52)

# Steps of a window: (the VERBS key, the STRINGS key of its text, the event kind).
STEPS = {
    "deploy": ("deploy", "step_deploy", "step"),
    "rollback": ("revert", "step_rollback", "start"),
    "forward": ("resume", "step_forward", "step"),
    "released": ("final", "step_released", "step"),
    "add": ("add", "step_add", "step"),
    "rename": ("rename", "step_rename", "step"),
    "drop": ("drop", "step_drop", "step"),
    "copied": ("copied", "step_copied", "step"),
    "read_new_on": ("reads", "step_read_new", "step"),
    "read_new_off": ("reads", "step_read_old", "step"),
    "write_old_off": ("writes", "step_write_new", "step"),
    "write_old_on": ("writes", "step_write_both", "step"),
    "lag_start": ("lag", "step_lag_start", "start"),  # trouble starting: shown like an incident, cause in full
    "lag_end": ("lag", "step_lag_end", "end"),
    "peak_start": ("busy", "step_peak_start", "start"),
    "peak_end": ("busy", "step_peak_end", "end"),
    "shunned": ("out", "step_shunned", "warn"),
    "back_in": ("back", "step_back_in", "step"),
    "done": ("done", "step_done", "ok"),
    "unfinished": ("stop", "step_unfinished", "warn"),
    "failed": ("fail", "step_failed", "warn"),
    "cut": ("stop", "step_cut", "warn"),
}


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _in_window(run: Run, inc: Incident, upto: float) -> list[tuple]:
    """Requests started in the window that had ended by `upto`."""
    return [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_END] <= upto]


def _errors(run: Run, inc: Incident, upto: float):
    rows = _in_window(run, inc, upto)
    if not rows:
        return None, "–"
    n = sum(r[REQ_OUTCOME] == ERROR for r in rows)
    return n, fmt_int(n)


def _errors_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return bool(_errors(run, inc, upto)[0])


def _writes(run: Run, inc: Incident, upto: float) -> list[float]:
    """How long each write started in the window took (still waiting at `upto`: so far)."""
    return [min(r[REQ_END], upto) - r[REQ_START] for r in run.rows("requests", inc.t0, min(inc.t1, upto))
            if r[REQ_KIND] == WRITE and (r[REQ_END] <= upto or upto - r[REQ_START] > lab.P99_MAX)]


def _p99(run: Run, inc: Incident, upto: float):
    v = percentile(_writes(run, inc, upto), 99)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _p99_doomed(run: Run, inc: Incident, upto: float) -> bool:
    """More writes were slow already than 1% of all the writes the window will see: it cannot pass."""
    seen = min(inc.t1, upto) - inc.t0
    if seen < 2.0:
        return False
    took = _writes(run, inc, upto)
    slow = sum(d > lab.P99_MAX for d in took)
    return slow > 0.02 * len(took) * (inc.t1 - inc.t0) / seen  # twice what would fail: never a wrong alert


def window_row(run: Run, index: int) -> tuple | None:
    return run.data.get("windows", {}).get(index)


def _wrong(run: Run, inc: Incident, upto: float):
    """Reads that returned a wrong name during the window, plus the rows left with a wrong name in
    the column the app reads at the end."""
    rows = _in_window(run, inc, upto)
    n = sum(r[REQ_OUTCOME] == WRONG for r in rows)
    w = window_row(run, inc.index)
    if w is not None and w[W_T1] <= upto:
        n += w[W_WRONG]
    elif not rows:
        return None, "–"
    return n, fmt_int(n)


def _wrong_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return bool(_wrong(run, inc, upto)[0])


def done_at(run: Run, inc: Incident, upto: float) -> float | None:
    for s in run.data.get("done", {}).get(inc.index, []):
        if s <= upto:
            return s
    return None


def _done(run: Run, inc: Incident, upto: float):
    """How long after the window opened the migration was done (the old column dropped)."""
    at = done_at(run, inc, upto)
    if at is not None:
        return at - inc.t0, f"{at - inc.t0:.0f}s"
    return None, _s("not_done") if upto >= inc.t1 else "–"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _window, _errors, lambda v: v is not None and v <= lab.ERRORS_MAX,
             doomed=_errors_doomed, settle_extra=lab.SETTLE, key="errors"),
    GoalSpec("", "during", "", _window, _p99, lambda v: v is not None and v <= lab.P99_MAX,
             doomed=_p99_doomed, settle_extra=lab.SETTLE, key="p99"),
    GoalSpec("", "after", "", _window, _wrong, lambda v: v is not None and v <= lab.WRONG_MAX,
             doomed=_wrong_doomed, settle_extra=lab.SETTLE, key="wrong"),
    GoalSpec("", "after", "", _window, _done, lambda v: v is not None and v <= lab.WINDOW,
             settle_extra=lab.SETTLE, key="done"),
]


class ZeroDowntimeMigrationWorld(World):
    id = "zero_downtime_migration"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "waiting"), (EXTRA2, "slow"), (GREEN, "served"), (RED, "failed"),
              (EXTRA3, "wrong"), (BACKFILL_KEY, "backfill", "█"), (TROUBLE_KEY, "trouble", "█")]
    incident_verbs = ("open", "close")
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "samples": Table(sort=S_T, times=(S_T,)),
        "steps": Table(sort=ST_T, times=(ST_T,)),
        "windows": Table(sort=W_T1, times=(W_T1,)),
    }
    goals = GOALS
    chart_top = 100.0

    @property
    def rows_n(self) -> int:
        return int(self.params.get("rows", 10_000))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        writes: dict[int, list[float]] = {}
        for r in tables["requests"]:
            name = {OK: "served", ERROR: "failed", WRONG: "wrong"}[r[REQ_OUTCOME]]
            run.add(name, r[REQ_END])
            if r[REQ_KIND] == WRITE:
                writes.setdefault(int(r[REQ_START]), []).append(r[REQ_END] - r[REQ_START])
        for s, took in writes.items():  # every second is in one piece: its p99 is final
            run.add("p99", s, percentile(took, 99) or 0.0)
        for x in tables["samples"]:
            run.add("load_traffic", x[S_T], 100 * x[S_TRAFFIC] * SAMPLE)
            run.add("load_other", x[S_T], 100 * x[S_OTHER] * SAMPLE)
            run.add("load_bf", x[S_T], 100 * x[S_BF] * SAMPLE)
            run.add("wrong_rows", x[S_T], x[S_WRONG] * SAMPLE)
            spans = run.data.setdefault("spans", [])  # [start, end, kind]: copies running, trouble
            for kind, on in (("bf", x[S_RUNNING]), ("trouble", x[S_TROUBLE] != 0)):
                last = next((sp for sp in reversed(spans) if sp[2] == kind), None)
                if on and last is not None and last[1] >= x[S_T] - SAMPLE - 1e-6:
                    last[1] = x[S_T] + SAMPLE
                elif on:
                    spans.append([x[S_T], x[S_T] + SAMPLE, kind])
        done = run.data.setdefault("done", {})
        ends = run.data.setdefault("ends", {})  # window -> (when, how) its migration ended
        for st in tables["steps"]:
            if st[ST_KEY] == "done":
                done.setdefault(st[ST_WINDOW], []).append(st[ST_T])
            if st[ST_KEY] in ("done", "failed", "cut", "unfinished"):
                ends.setdefault(st[ST_WINDOW], (st[ST_T], st[ST_KEY]))
            ev = self._step_event(run, st)
            if ev is not None:
                run.timeline.append(ev)
        run.timeline.sort(key=_event_order)
        wins = run.data.setdefault("windows", {})
        for w in tables["windows"]:
            wins[w[W_INDEX]] = w

    def _step_event(self, run: Run, st: tuple) -> TimelineEvent | None:
        spec = STEPS.get(st[ST_KEY])
        if spec is None:
            return None
        verb, key, kind = spec
        k = st[ST_WINDOW]
        old, new = rename(k)
        inc = run.incidents[k] if k < len(run.incidents) else None
        detail = st[ST_DETAIL]
        values = {"old": old, "new": new, "v": detail, "col": detail, "cause": self._cause(detail),
                  "s": 0.0 if inc is None else st[ST_T] - inc.t0, "lag": SHUN}
        if st[ST_KEY] == "failed":
            values["why"] = self.s(f"err_{detail[0]}", col=detail[1])
        colour = {"warn": EXTRA2, "ok": GREEN, "start": RED}.get(kind, BLUE)
        return TimelineEvent(st[ST_T], self.word(verb), self.s(key, **values), colour, k, kind=kind)

    def _cause(self, key) -> str:
        return getattr(self.text, "CAUSES", {}).get(key, "") if isinstance(key, str) else ""

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.incident_name, n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        old, new = rename(inc.index)
        if not start:
            return self.s("closed")
        if inc.kind == "deploy":
            return self.s("open_cause", old=old, new=new, cause=self.cause(inc))
        return self.s("open", old=old, new=new)

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def bands(self, variant: str, t: float):
        run = self.runs.get(variant)
        if run is None:
            return []
        colours = {"bf": BACKFILL_BAND, "trouble": TROUBLE_BAND}
        out = [(a, min(b, t), colours[kind]) for a, b, kind in run.data.get("spans", []) if a <= t and b > t - 70]
        return sorted(out, key=lambda x: x[2] == BACKFILL_BAND)  # trouble first: it wins where both are

    # ---------------------------------------------------------------- the state at t

    def sample_at(self, run: Run, t: float) -> tuple | None:
        rows = run.rows("samples", t - 2 * SAMPLE, t + 1e-9)
        return rows[-1] if rows else None

    def columns(self, run: Run, t: float) -> tuple[str, str, int]:
        """(old, new, schema bits) of the column traffic uses at t."""
        x = self.sample_at(run, t)
        k = x[S_FIELD] if x else 0
        old, new = rename(k)
        return old, new, (x[S_BITS] if x else HAS_OLD)

    def recent(self, run: Run, t: float, span: float = 5.0) -> list[tuple]:
        """Requests that ended in [t - span, t)."""
        longest = run.max_dur.get("requests", 0.0)
        return [r for r in run.rows("requests", t - span - longest, t) if t - span <= r[REQ_END] < t]

    def load_at(self, run: Run, t: float) -> float:
        x = self.sample_at(run, t)
        return 0.0 if x is None else min(0.95, x[S_TRAFFIC] + x[S_OTHER] + x[S_BF])

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        last5 = self.recent(run, t)
        errors = sum(r[REQ_OUTCOME] == ERROR for r in last5)
        inc = self.incident_at(variant, t)
        if inc is not None and t - inc.t0 >= 5.0:  # in a window: its p99 so far, like the goal
            p99 = percentile(_writes(run, inc, t), 99)
        else:
            p99 = percentile([r[REQ_END] - r[REQ_START] for r in last5 if r[REQ_KIND] == WRITE], 99)
        x = self.sample_at(run, t)
        stale = x[S_WRONG] if x else 0
        reads_new = bool(x and x[S_BITS] & READS_NEW)
        wrong_reads = sum(r[REQ_OUTCOME] == WRONG for r in last5)

        def err_s(s: int):
            n = run.series("failed", s, s + 1)[0]
            return n, "bad" if n else "ok"

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.P99_MAX else "warn" if v > 0.75 * lab.P99_MAX else "ok"

        def p99_s(s: int):
            v = run.series("p99", s, s + 1)[0]
            return v, p99_state(v) if v else "idle"

        def wrong_state(rows: float, reads: float, on_new: bool) -> str:
            if reads or (rows and on_new):
                return "bad"
            return "warn" if rows else "ok"

        def wrong_s(s: int):
            rows, reads = run.series("wrong_rows", s, s + 1)[0], run.series("wrong", s, s + 1)[0]
            return rows + reads, wrong_state(rows, reads, False)

        tiles = [
            Tile(self.s("tile_errors"), fmt_int(errors), "=0", "bad" if errors else "ok", history(run, t, err_s)),
            Tile(self.s("tile_p99"), fmt_ms(p99), "<40ms", p99_state(p99), history(run, t, p99_s)),
            Tile(self.s("tile_wrong"), fmt_int(stale + wrong_reads), "=0",
                 wrong_state(stale, wrong_reads, reads_new), history(run, t, wrong_s)),
        ]
        last1 = [r for r in last5 if r[REQ_END] >= t - 1.0]
        reads_old = sum(1 for r in last1 if r[REQ_KIND] != WRITE and r[REQ_COLS] & OLD_COL)
        writes_old = sum(1 for r in last1 if r[REQ_KIND] == WRITE and r[REQ_COLS] & OLD_COL)
        reads_new_n = sum(1 for r in last1 if r[REQ_KIND] != WRITE and r[REQ_COLS] & NEW_COL)
        writes_new = sum(1 for r in last1 if r[REQ_KIND] == WRITE and r[REQ_COLS] & NEW_COL)
        failed = sum(1 for r in last1 if r[REQ_OUTCOME] == ERROR)
        bars = [Bar(self.s("bar_old"), [(reads_old, WHITE), (writes_old, BLUE)]),
                Bar(self.s("bar_new"), [(reads_new_n, WHITE), (writes_new, BLUE)]),
                Bar(self.s("bar_failed"), [(failed, RED)])]
        headline, colour = self._headline(variant, run, t, last1)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("bars"), subtitle=self.s("bars_sub"))

    def _headline(self, variant: str, run: Run, t: float, last1: list[tuple]):
        x = self.sample_at(run, t)
        inc = self.incident_at(variant, t)
        old, new, bits = self.columns(run, t)
        if any(r[REQ_OUTCOME] == ERROR for r in last1):
            return self.s("head_errors"), RED
        writes = [r[REQ_END] - r[REQ_START] for r in last1 if r[REQ_KIND] == WRITE]
        stuck = sum(1 for r in run.active("requests", t, REQ_END)
                    if r[REQ_KIND] == WRITE and t - r[REQ_START] > lab.P99_MAX)  # e.g. behind a copy's locks
        if stuck >= 3 or (writes and sum(d > lab.P99_MAX for d in writes) > 0.05 * len(writes)):
            if x is not None and x[S_SHUNNED]:
                return self.s("head_shunned"), RED
            return self.s("head_slow"), RED
        if any(r[REQ_OUTCOME] == WRONG for r in last1):
            return self.s("head_wrong_reads"), RED
        if inc is None or x is None:
            return self.s("head_calm"), MUTED
        if x[S_RUNNING]:
            return self.s("head_copying", pct=100 * x[S_COPIED] / max(1, self.rows_n)), BLUE
        if x[S_WRONG] and not bits & READS_NEW:
            return self.s("head_stale", n=x[S_WRONG]), EXTRA2
        if bits & HAS_NEW and not bits & HAS_OLD:
            return self.s("head_done", old=old, new=new), BLUE
        if bits & HAS_NEW and x[S_TROUBLE] and x[S_COPIED] < self.rows_n:
            return self.s("head_paused"), EXTRA2
        if x[S_OLD] and x[S_NEW]:
            return self.s("head_mixed", old=x[S_OLD], new=x[S_NEW], va=x[S_BASE], vb=x[S_BASE] + 1), MUTED
        return self.s("head_window", old=old, new=new), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("requests", 0.0)
        partial = [r for r in run.rows("requests", s - span - 1, t) if s <= r[REQ_END] < t]
        served = run.total("served", t) + sum(1 for r in partial if r[REQ_OUTCOME] == OK)
        failed = run.total("failed", t) + sum(1 for r in partial if r[REQ_OUTCOME] == ERROR)
        wrong = run.total("wrong", t) + sum(1 for r in partial if r[REQ_OUTCOME] == WRONG)
        last5 = self.recent(run, t)
        took = [r[REQ_END] - r[REQ_START] for r in last5]
        writes = [r[REQ_END] - r[REQ_START] for r in last5 if r[REQ_KIND] == WRITE]
        words = self.screen.STATS
        return [
            (words["served"], fmt_int(served), GREEN),
            (words["failed"], fmt_int(failed), RED if failed else MUTED),
            (self.s("stat_wrong"), fmt_int(wrong), EXTRA3 if wrong else MUTED),
            (words["p50"], fmt_ms(percentile(took, 50)), WHITE),
            (self.s("stat_write_p99"), fmt_ms(percentile(writes, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("load_traffic", [])), (EXTRA2, run.hist.get("load_other", [])),
                (PURPLE, run.hist.get("load_bf", []))]

    def chart_limit(self):
        return 100 * lab.LOAD_LIMIT, self.s("limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = ZeroDowntimeMigrationWorld
