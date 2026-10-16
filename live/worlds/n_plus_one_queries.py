"""World for lab n_plus_one_queries. Its words are in labs/n_plus_one_queries/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.n_plus_one_queries import lab
from labs.n_plus_one_queries.scenario import JOIN, LIST, MANY, ONE
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, IDLE_DOT, MUTED, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, below,
    history, percentile,
)

PAGE_ID, PAGE_START, PAGE_END, PAGE_OK, PAGE_ITEMS, PAGE_QUERIES = range(6)
Q_QUEUED, Q_PAGE, Q_KIND, Q_START, Q_END = range(5)
SEC, SEC_LIST, SEC_ONE, SEC_MANY, SEC_JOIN, SEC_BUSY = range(6)
INCIDENT_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
KIND_COLOUR = {LIST: WHITE, ONE: EXTRA2, MANY: EXTRA1, JOIN: BLUE}
INF = float("inf")

_s = strings("n_plus_one_queries")  # one of the lab's STRINGS, for the goal measures below


def _page_time(p: tuple) -> float:
    return p[PAGE_END] - p[PAGE_START] if p[PAGE_OK] else INF


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Pages that ended in [a, b)."""
    span = run.max_dur.get("pages", 0.0)
    return [p for p in run.rows("pages", a - span, b) if a <= p[PAGE_END] < b]


def _busy(run: Run, a: float, b: float) -> float | None:
    """Share of the database's connections busy over whole seconds in [a, b)."""
    secs = run.series("busy", int(a), max(int(a) + 1, int(b)))
    return sum(secs) / (lab.CONNECTIONS * len(secs)) if secs else None


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER_WINDOW


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    pages = _ended(run, a, min(b, upto))
    if not pages:
        return NO_VALUE
    v = sum(p[PAGE_OK] for p in pages) / len(pages)
    return v, f"{v:.0%}"


def _queries(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    pages = _ended(run, a, min(b, upto))
    if not pages:
        return NO_VALUE
    v = sum(p[PAGE_QUERIES] for p in pages) / len(pages)
    return v, f"{v:.1f}"


def _db_busy(run: Run, inc: Incident, upto: float):
    b = min(inc.t1, upto)
    if b <= inc.t0:
        return NO_VALUE
    v = _busy(run, inc.t0, b)
    return v, "–" if v is None else f"{v:.0%}"


def _busy_doomed(run: Run, inc: Incident, upto: float) -> bool:
    # Even with an idle database for the rest of the incident, it was busy too long.
    seconds = max(1, int(inc.t1) - int(inc.t0))
    so_far = sum(run.series("busy", int(inc.t0), int(min(inc.t1, upto))))
    return so_far >= lab.BUSY_MAX * lab.CONNECTIONS * seconds


def _p99(run: Run, inc: Incident, upto: float):
    times = [_page_time(p) for p in run.rows("pages", inc.t0, min(inc.t1, upto)) if p[PAGE_END] <= upto]
    v = percentile(times, 99)
    if v is None:
        return NO_VALUE
    return v, "> 2s" if v == INF else f"{v * 1000:.0f}ms"


def _served(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    pages = [p for p in run.rows("pages", a, min(b, upto)) if p[PAGE_END] <= upto]
    if not pages:
        return NO_VALUE
    v = sum(p[PAGE_OK] for p in pages) / len(pages)
    return v, f"{v:.0%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN),
             key="baseline"),
    GoalSpec("", "before", "", _before, _queries, at_most(lab.QUERIES_MAX),
             key="queries"),
    GoalSpec("", "during", "", _during, _db_busy, below(lab.BUSY_MAX),
             doomed=_busy_doomed, key="busy"),
    GoalSpec("", "during", "", _during, _p99, below(lab.P99_MAX),
             settle_extra=2.5, key="p99"),
    GoalSpec("", "after", "", _after, _served, at_least(lab.SERVED_MIN),
             settle_extra=2.5, key="served"),
]


class NPlusOneWorld(World):
    id = "n_plus_one_queries"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "list"), (EXTRA2, "per_item"), (EXTRA1, "batch"),
              (BLUE, "join"), (GREEN, "served"), (RED, "failed"), (INCIDENT_KEY, "incident", "█")]
    tables = {
        "pages": Table(sort=PAGE_START, times=(PAGE_START, PAGE_END)),
        "queries": Table(sort=Q_QUEUED, times=(Q_QUEUED, Q_END)),
        "secs": Table(sort=SEC, times=(SEC,)),
    }
    goals = GOALS

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for p in tables["pages"]:
            run.add("pages", p[PAGE_START])
            run.add("served" if p[PAGE_OK] else "failed", p[PAGE_END])
        for row in tables["secs"]:
            t = row[SEC]
            for name, col in (("q_list", SEC_LIST), ("q_one", SEC_ONE), ("q_many", SEC_MANY), ("q_join", SEC_JOIN)):
                run.add(name, t, row[col])
            run.add("queries", t, row[SEC_LIST] + row[SEC_ONE] + row[SEC_MANY] + row[SEC_JOIN])
            run.add("busy", t, row[SEC_BUSY])

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        keys = {"slow_db": ("slow", "fast"), "big_pages": ("big", "normal"), "spike": ("spike", "calm")}
        return self.word(keys[inc.kind][0 if start else 1])

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        if inc.kind == "slow_db":
            return self.s("slow_db", ms=inc.severity, cause=self.cause(inc))
        return self.s(inc.kind, times=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1)):
            busy = run.series("busy", s, s + 1)[0] / lab.CONNECTIONS
            if busy >= lab.BUSY_MAX:
                return [(s + 1.0, self.s("warn_busy", busy=busy))]
        return []

    def busy_at(self, run: Run, t: float) -> float:
        """Share of connections busy in the last whole second."""
        return run.series("busy", int(t) - 1, int(t))[0] / lab.CONNECTIONS

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        recent = _ended(run, t - 5, t)
        qpp = sum(p[PAGE_QUERIES] for p in recent) / len(recent) if recent else 0.0

        def q_state(v: float) -> str:
            return "bad" if v > lab.QUERIES_MAX else "warn" if v > 1 else "ok"

        def q_s(s: int):
            pages, queries = run.series("pages", s, s + 1)[0], run.series("queries", s, s + 1)[0]
            v = queries / pages if pages else 0.0
            return v, q_state(v) if pages else "idle"

        p99 = percentile([_page_time(p) for p in recent], 99)

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.P99_MAX / 2 else "ok"

        def p99_s(s: int):
            v = percentile([_page_time(p) for p in _ended(run, s, s + 1)], 99)
            return (min(v, 1.0) if v is not None else 0.0), p99_state(v)

        busy = self.busy_at(run, t)

        def busy_state(v: float) -> str:
            return "bad" if v >= lab.BUSY_MAX else "warn" if v >= 0.6 else "ok"

        def busy_s(s: int):
            v = run.series("busy", s, s + 1)[0] / lab.CONNECTIONS
            return v, busy_state(v)

        p99_text = "–" if p99 is None else "> 2s" if p99 == INF else f"{p99 * 1000:.0f}ms"
        tiles = [
            Tile(self.s("tile_queries"), f"{qpp:.1f}", "≤2", q_state(qpp), history(run, t, q_s)),
            Tile(self.s("tile_p99"), p99_text, "<40ms", p99_state(p99), history(run, t, p99_s)),
            Tile(self.s("tile_busy"), f"{busy:.0%}", "<90%", busy_state(busy), history(run, t, busy_s)),
        ]
        s = int(t) - 1
        kinds = [(run.series(name, s, s + 1)[0], colour) for name, colour in
                 (("q_list", WHITE), ("q_many", EXTRA1), ("q_join", BLUE), ("q_one", EXTRA2))]
        bars = [Bar(self.s("bar_pages"), [(run.series("pages", s, s + 1)[0], WHITE)]),
                Bar(self.s("bar_queries"), kinds)]
        inc = self.incident_at(variant, t)
        if busy >= lab.BUSY_MAX:
            headline, colour = self.s("head_busy", busy=busy), RED
        elif inc is not None and inc.kind == "slow_db":
            headline, colour = self.s("head_slow", qpp=qpp, p99=p99_text), EXTRA2 if qpp > 1 else BLUE
        else:
            headline, colour = self.s("head_calm", qpp=qpp), MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("toplist"))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "pages", PAGE_START, PAGE_END, PAGE_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("q_list", [])), (EXTRA1, run.hist.get("q_many", [])),
                (BLUE, run.hist.get("q_join", [])), (EXTRA2, run.hist.get("q_one", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = NPlusOneWorld
