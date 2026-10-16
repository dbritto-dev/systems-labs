"""World for lab keyset_pagination. Its words are in labs/keyset_pagination/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.keyset_pagination import lab
from labs.keyset_pagination.api import OVERHEAD, ROW_COST, WORKERS
from labs.keyset_pagination.scenario import BAD, OK, SYNC
from live.canvas import (
    BLUE, EXTRA, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, PURPLE, RED, WHITE,
)
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, fmt_int,
    fmt_ms, history, percentile,
)

INCIDENT_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

(P_START, P_ID, P_END, P_WALK, P_DEPTH, P_KIND, P_READ, P_RET, P_SKIPPED, P_DUP,
 P_OUTCOME, P_API) = range(12)
Q_START, Q_END, Q_READ, Q_WORKER, Q_PAGE = range(5)
W_T, W_INS, W_DEL, W_TIED, W_SIZE = range(5)

_s = strings("keyset_pagination")  # one of the lab's STRINGS, for the goal measures below


def rows_text(v: float) -> str:
    """Rows read per page, short enough for a tile: 20, 950, 9,999, 44k."""
    return fmt_int(v) if v < 10_000 else f"{v / 1000:.0f}k"


def page_colour(p: tuple):
    """What a page did, at the door: skipped posts red, repeated posts purple, a 400 grey, else green."""
    if p[P_SKIPPED]:
        return RED
    if p[P_DUP]:
        return PURPLE
    return MUTED if p[P_OUTCOME] == BAD else GREEN


def cost_colour(read: int):
    """How many rows a page made the database read: white about a page, deeper orange for more."""
    return EXTRA[lab.bucket(read)]


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _ended(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Pages asked for in [a, b) that came back by `upto`."""
    return [p for p in run.rows("pages", a, min(b, upto)) if p[P_END] <= upto]


def _baseline(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_before(inc), upto)
    if not done:
        return NO_VALUE
    v = sum(p[P_OUTCOME] == OK for p in done) / len(done)
    return v, f"{v:.0%}" if v < 0.995 or v == 1 else f"{v:.1%}"


def _count(col: int):
    def measure(run: Run, inc: Incident, upto: float):
        done = _ended(run, *_during(inc), upto)
        if not done:
            return NO_VALUE
        n = sum(p[col] for p in done)
        return n, _s("count", n=n)

    return measure


def _doomed(col: int):
    return lambda run, inc, upto: any(p[col] for p in _ended(run, *_during(inc), upto))


def _deep(run: Run, inc: Incident, upto: float):
    """p99 of the deep pages (a walk's 10th page or later): OFFSET makes them read thousands of rows."""
    v = percentile([p[P_END] - p[P_START] for p in _ended(run, *_during(inc), upto)
                    if p[P_DEPTH] >= lab.DEEP_PAGE], 99)
    if v is None:
        return NO_VALUE
    return v, fmt_ms(v)


def _rows(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_during(inc), upto)
    if not done:
        return NO_VALUE
    v = sum(p[P_READ] for p in done) / len(done)
    return v, rows_text(v)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), key="baseline"),
    GoalSpec("", "during", "", _during, _count(P_SKIPPED), lambda v: v == 0,
             doomed=_doomed(P_SKIPPED), settle_extra=lab.SETTLE, key="skipped"),
    GoalSpec("", "during", "", _during, _count(P_DUP), lambda v: v == 0,
             doomed=_doomed(P_DUP), settle_extra=lab.SETTLE, key="dup"),
    GoalSpec("", "during", "", _during, _deep,
             lambda v: v is None or v < lab.DEEP_P99_MAX, settle_extra=lab.SETTLE, key="deep"),
    GoalSpec("", "during", "", _during, _rows, at_most(lab.ROWS_MAX), settle_extra=lab.SETTLE, key="rows"),
]


class KeysetPaginationWorld(World):
    id = "keyset_pagination"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "cheap"), ([EXTRA1, EXTRA2, EXTRA3], "scans"),
              (RED, "skipped"), (PURPLE, "repeated"), (GREEN, "served"), (LIMIT, "limit", "┄"),
              (INCIDENT_KEY, "incident", "█")]
    chart_top = 100.0
    tables = {
        "pages": Table(sort=P_START, times=(P_START, P_END)),
        "queries": Table(sort=Q_START, times=(Q_START, Q_END)),
        "writes": Table(sort=W_T, times=(W_T,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 10.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for p in tables["pages"]:
            run.add("asks", p[P_START])
            run.add("served" if p[P_OUTCOME] == OK else "failed", p[P_END])
            run.add("pages", p[P_END])
            run.add("read", p[P_END], p[P_READ])
            if p[P_SKIPPED]:
                run.add("skipped", p[P_END], p[P_SKIPPED])
            if p[P_DUP]:
                run.add("dup", p[P_END], p[P_DUP])
            # Database time, as a share of all the workers, in the second it was asked for.
            busy = (OVERHEAD + p[P_READ] * ROW_COST) / WORKERS * 100
            run.add(f"b{lab.bucket(p[P_READ])}", p[P_START], busy)
        for w in tables["writes"]:
            run.add("inserts", w[W_T], w[W_INS])
            run.add("deletes", w[W_T], w[W_DEL])
            run.add("tied", w[W_T], w[W_TIED])
        if tables["writes"]:
            run.data["size"] = tables["writes"][-1][W_SIZE]

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", n=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        done = run.rows("pages", inc.t0, inc.t1)
        skipped, dup = sum(p[P_SKIPPED] for p in done), sum(p[P_DUP] for p in done)
        out = []
        if skipped:
            out.append((inc.t1, self.s("warn_skipped", n=skipped)))
        if dup:
            out.append((inc.t1, self.s("warn_dup", n=dup)))
        return out

    def ended(self, run: Run, a: float, b: float) -> list[tuple]:
        """Pages that came back in [a, b)."""
        span = run.max_dur.get("pages", 0.0)
        return [p for p in run.rows("pages", a - span, b) if a <= p[P_END] < b]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        s = int(t)
        recent = self.ended(run, t - 10, t)
        skipped = sum(p[P_SKIPPED] for p in recent)
        dup = sum(p[P_DUP] for p in recent)
        pages, read = sum(run.series("pages", s - 5, s)), sum(run.series("read", s - 5, s))
        per_page = read / pages if pages else None

        def count_s(name: str):
            def fn(k: int):
                v = run.series(name, k, k + 1)[0]
                return v, "bad" if v else "ok"

            return fn

        def rows_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.ROWS_MAX else "ok"

        def rows_s(k: int):
            n, r = run.series("pages", k, k + 1)[0], run.series("read", k, k + 1)[0]
            v = r / n if n else None
            return v or 0.0, rows_state(v)

        tiles = [
            Tile(self.s("tile_skipped"), fmt_int(skipped), "=0", "bad" if skipped else "ok",
                 history(run, t, count_s("skipped"))),
            Tile(self.s("tile_dup"), fmt_int(dup), "=0", "bad" if dup else "ok", history(run, t, count_s("dup"))),
            Tile(self.s("tile_rows"), "–" if per_page is None else rows_text(per_page), f"≤{lab.ROWS_MAX}",
                 rows_state(per_page), history(run, t, rows_s)),
        ]

        last = self.ended(run, t - 1, t)

        def segments(kind: int) -> list[tuple[float, tuple]]:
            n = {GREEN: 0, RED: 0, PURPLE: 0, MUTED: 0}
            for p in last:
                if (p[P_KIND] == SYNC) == (kind == SYNC):
                    n[page_colour(p)] += 1
            return [(float(c), colour) for colour, c in n.items()]

        bars = [
            Bar(self.s("bar_readers"), segments(0)),
            Bar(self.s("bar_sync"), segments(SYNC)),
            Bar(self.s("bar_posts"), [(run.series("inserts", s - 1, s)[0], WHITE),
                                      (run.series("tied", s - 1, s)[0], BLUE),
                                      (run.series("deletes", s - 1, s)[0], EXTRA2)]),
        ]
        headline, colour = self._headline(variant, run, t, recent, last)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("title"))

    def _headline(self, variant: str, run: Run, t: float, recent: list[tuple], last: list[tuple]):
        skipped = sum(p[P_SKIPPED] for p in recent)
        if skipped:
            return self.s("head_skipped", n=skipped), RED
        dup = sum(p[P_DUP] for p in recent)
        if dup:
            return self.s("head_dup", n=dup), PURPLE
        deepest = max(last, key=lambda p: p[P_READ], default=None)
        if deepest is not None and deepest[P_READ] > lab.ROWS_MAX:
            return self.s("head_deep", page=deepest[P_DEPTH] + 1, rows=deepest[P_READ]), EXTRA2
        inc = self.incident_at(variant, t)
        if inc is not None:
            return self.s(f"head_{inc.kind}"), BLUE
        return self.s("head_ok", rows=run.data.get("size", 0)), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        stats = self.request_stats(run, "pages", P_START, P_END, P_OUTCOME, t)
        deep = [p[P_END] - p[P_START] for p in self.ended(run, t - 5, t) if p[P_DEPTH] >= lab.DEEP_PAGE]
        stats[3] = (self.s("stat_deep"), fmt_ms(percentile(deep, 99)), WHITE)
        return stats

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA[k], run.hist.get(f"b{k}", [])) for k in range(4)]

    def chart_limit(self):
        return 100.0, "100%"

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = KeysetPaginationWorld
