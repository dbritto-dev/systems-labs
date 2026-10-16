"""World for lab database_index. Its words are in labs/database_index/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.database_index import lab
from labs.database_index.scenario import INSERT, LOOKUP, RANGE
from live.canvas import BLUE, EXTRA, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, below, fmt_int, fmt_ms,
    history, percentile,
)

INCIDENT_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

_s = strings("database_index")  # one of the lab's STRINGS, for the goal measures below

Q_START, Q_ID, Q_KIND, Q_READ, Q_RET, Q_END, Q_OK, Q_RAN = range(8)


def rows_text(v: float) -> str:
    """Rows read, short enough for a tile: 1, 950, 9,999, 44k."""
    return fmt_int(v) if v < 10_000 else f"{v / 1000:.0f}k"


def ratio_text(v: float) -> str:
    """Rows read per row returned: 1.0x, 12.5x, 955x."""
    return _s("ratio", value=v) if v < 100 else f"{v:,.0f}x"


def _latency(q: tuple) -> float:
    """How long the user waited: a query that gave up never got an answer."""
    return q[Q_END] - q[Q_START] if q[Q_RAN] else float("inf")


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE_WINDOW, inc.t0


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _ran(run: Run, kind: int, a: float, b: float) -> list[tuple]:
    return [q for q in run.rows("queries", a, b) if q[Q_KIND] == kind and q[Q_RAN]]


def _lookups(run: Run, inc: Incident, upto: float):
    """Rows read per login, on average: a full scan reads the whole table, an index one row."""
    a, b = _before(inc)
    rows = _ran(run, LOOKUP, a, min(b, upto))
    if not rows:
        return NO_VALUE
    v = sum(q[Q_READ] for q in rows) / len(rows)
    return v, rows_text(v)


def _ranges(run: Run, inc: Incident, upto: float):
    """Rows read per row returned by a range query: 1x when an index finds just those rows."""
    a, b = _before(inc)
    rows = _ran(run, RANGE, a, min(b, upto))
    if not rows:
        return NO_VALUE
    v = sum(q[Q_READ] for q in rows) / sum(max(1, q[Q_RET]) for q in rows)
    return v, ratio_text(v)


def _ended(run: Run, inc: Incident, upto: float) -> list[tuple]:
    """Queries started during the incident that have an outcome by `upto`."""
    return [q for q in run.rows("queries", inc.t0, min(inc.t1, upto)) if q[Q_END] <= upto]


def _p99(run: Run, inc: Incident, upto: float):
    rows = _ended(run, inc, upto)
    if not rows:
        return NO_VALUE
    v = percentile([_latency(q) for q in rows], 99)
    return v, _s("timeouts") if v == float("inf") else fmt_ms(v)


def _answered(run: Run, inc: Incident, upto: float):
    rows = _ended(run, inc, upto)
    if not rows:
        return NO_VALUE
    v = sum(q[Q_OK] for q in rows) / len(rows)
    return v, f"{v:.0%}" if v < 0.995 or v == 1 else f"{v:.1%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _lookups, at_most(lab.LOOKUP_MAX), key="lookups"),
    GoalSpec("", "before", "", _before, _ranges, at_most(lab.RANGE_MAX), key="ranges"),
    GoalSpec("", "during", "", _during, _p99, below(lab.P99_MAX), settle_extra=lab.SETTLE, key="p99"),
    GoalSpec("", "during", "", _during, _answered, at_least(lab.ANSWERED_MIN), settle_extra=lab.SETTLE, key="answered"),
]


class DbIndexWorld(World):
    id = "database_index"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "cheap"), ([EXTRA1, EXTRA2, EXTRA3], "costly"),
              (RED, "timed_out"), (GREEN, "served"), (LIMIT, "limit", "┄"), (INCIDENT_KEY, "incident", "█")]
    chart_top = 100.0
    incident_verbs = ("import", "calm")  # the start verb is the incident's kind: see incident_verb
    tables = {
        "queries": Table(sort=Q_START, times=(Q_START, Q_END)),
        "writes": Table(sort=Q_START, times=(Q_START, Q_END)),
        "size": Table(sort=0, times=(0,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 30.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for q in tables["queries"] + tables["writes"]:
            kind, start = q[Q_KIND], q[Q_START]
            run.add({LOOKUP: "lookups", RANGE: "ranges", INSERT: "writes"}[kind], start)
            if not q[Q_RAN]:
                run.add("timeouts", q[Q_END])
            else:
                # Database time, as a share of all the workers, in the second it was asked for.
                busy = (lab.OVERHEAD + q[Q_READ] * lab.ROW_COST) / lab.WORKERS * 100
                run.add(f"b{lab.bucket(q[Q_READ])}", start, busy)
                if kind == LOOKUP:
                    run.add("l_read", start, q[Q_READ])
                    run.add("l_n", start)
                elif kind == RANGE:
                    run.add("r_read", start, q[Q_READ])
                    run.add("r_ret", start, max(1, q[Q_RET]))
            if kind != INSERT:
                run.add("served" if q[Q_OK] else "failed", q[Q_END])
        for t, n in tables["size"]:
            run.add("size", t, n)

    def _p99_second(self, run: Run, s: int) -> float | None:
        span = run.max_dur.get("queries", 0.0)
        return percentile([_latency(q) for q in run.rows("queries", s - span - 1, s + 1) if s <= q[Q_END] < s + 1],
                          99)

    def warnings(self, run: Run, inc: Incident):
        out = []
        for s in range(int(inc.t0), int(inc.t1) + 1):
            if run.series("timeouts", s, s + 1)[0]:
                out.append((s + 1.0, self.s("warn_timeouts")))
                break
            p = self._p99_second(run, s)
            if not out and p is not None and p >= lab.P99_MAX:
                out.append((s + 1.0, self.s("warn_slow", ms=p * 1000)))
        return out

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s("end")
        return self.s(f"start_{inc.kind}", rows=inc.severity, x=inc.severity, cause=self.cause(inc))

    def size_at(self, run: Run, t: float) -> int:
        s = max(0, int(t) - 1)
        return int(run.series("size", s, s + 1)[0])

    def timeouts_at(self, run: Run, t: float) -> int:
        """Users who gave up waiting in the last second."""
        return sum(1 for q in run.rows("queries", t - 1 - lab.TIMEOUT, t) if not q[Q_RAN] and t - 1 <= q[Q_END] < t)

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        s = int(t)

        def ratio(num: str, den: str, a: int, b: int) -> float | None:
            d = sum(run.series(den, a, b))
            return sum(run.series(num, a, b)) / d if d else None

        def lookup_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.LOOKUP_MAX else "ok"

        def lookup_s(k: int):
            v = ratio("l_read", "l_n", k, k + 1)
            return v or 0.0, lookup_state(v)

        def range_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.RANGE_MAX else "ok"

        def range_s(k: int):
            v = ratio("r_read", "r_ret", k, k + 1)
            return v or 0.0, range_state(v)

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.P99_MAX / 2 else "ok"

        def p99_s(k: int):
            v = self._p99_second(run, k)
            return min(v, lab.TIMEOUT) if v is not None else 0.0, p99_state(v)

        read = ratio("l_read", "l_n", s - 2, s)
        rng = ratio("r_read", "r_ret", s - 5, s)
        span = run.max_dur.get("queries", 0.0)
        recent = [_latency(q) for q in run.rows("queries", t - 5 - span, t) if t - 5 <= q[Q_END] < t]
        p99 = percentile(recent, 99)
        p99_text = "–" if p99 is None else self.s("timeouts") if p99 == float("inf") else fmt_ms(p99)
        tiles = [
            Tile(self.s("tile_lookup"), "–" if read is None else rows_text(read), "≤5", lookup_state(read),
                 history(run, t, lookup_s)),
            Tile(self.s("tile_range"), "–" if rng is None else ratio_text(rng), "≤2x", range_state(rng),
                 history(run, t, range_s)),
            Tile(self.s("tile_p99"), p99_text, "<100ms", p99_state(p99), history(run, t, p99_s)),
        ]

        def segments(kind: int) -> list[tuple[float, tuple]]:
            n = [0, 0, 0, 0]
            gave_up = 0
            for q in run.rows("queries", t - 1, t):
                if q[Q_KIND] != kind:
                    continue
                if q[Q_RAN]:
                    n[lab.bucket(q[Q_READ])] += 1
                else:
                    gave_up += 1
            return [(float(c), EXTRA[k]) for k, c in enumerate(n)] + [(float(gave_up), RED)]

        bars = [
            Bar(self.s("bar_logins"), segments(LOOKUP)),
            Bar(self.s("bar_ranges"), segments(RANGE)),
            Bar(self.s("bar_writes"), [(float(run.count("writes", t - 1, t)), WHITE)]),
        ]
        headline, colour = self._headline(variant, run, t, read)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("queries"))

    def _headline(self, variant: str, run: Run, t: float, read: float | None):
        gave_up = self.timeouts_at(run, t)
        if gave_up:
            return self.s("head_timeouts", n=gave_up), RED
        size = self.size_at(run, t)
        inc = self.incident_at(variant, t)
        if inc is not None and inc.kind == "import":
            return self.s("head_import", rows=size), BLUE
        if inc is not None and inc.kind == "report":
            return self.s("head_report"), BLUE
        if inc is not None and inc.kind == "spike":
            return self.s("head_spike", x=inc.severity), BLUE
        return self.s("head_calm", rows=size, read=read or 0), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "queries", Q_START, Q_END, Q_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA[k], run.hist.get(f"b{k}", [])) for k in range(4)]

    def chart_limit(self):
        return 100.0, "100%"

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = DbIndexWorld
