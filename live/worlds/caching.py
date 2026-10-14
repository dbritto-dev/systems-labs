"""World for lab caching. Its words are in labs/caching/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.caching import lab
from labs.caching.scenario import DUP, FAILED, HIT, MISS, SHARED
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, RGB, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, fmt_ms, history, percentile,
)

FLUSH_KEY = (110, 44, 56)  # the legend swatch for the shaded seconds after a flush


_s = strings("caching")  # one of the lab's STRINGS, for the goal measures below

PAGE_ID, PAGE_START, PAGE_END, PAGE_OK, PAGE_KIND = range(5)
READ_START, READ_PAGE, READ_KEY, READ_END, READ_OK, READ_KIND = range(6)
DB_QUEUED, DB_PAGE, DB_KEY, DB_START, DB_END, DB_OK, DB_DUP = range(7)

KIND_COLOUR: dict[int, RGB] = {HIT: WHITE, SHARED: EXTRA1, MISS: EXTRA2, DUP: EXTRA3, FAILED: RED}
INF = float("inf")


def _read_time(r: tuple) -> float:
    return r[READ_END] - r[READ_START] if r[READ_OK] else INF


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _hit_ratio(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    rows = run.rows("reads", a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(r[READ_KIND] == HIT for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t0 + lab.DURING_WINDOW


def _dups(run: Run, inc: Incident, upto: float):
    a, b = _during(inc)
    rows = run.rows("db", a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(r[DB_DUP] for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _seconds(a: float, b: float) -> list[float]:
    out, s = [], a
    while s < b:
        out.append(s)
        s += 1.0
    return out or [a]


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t0 + lab.AFTER_WINDOW


def _p99(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    times = [_read_time(r) for r in run.rows("reads", a, min(b, upto)) if r[READ_END] <= upto]
    v = percentile(times, 99)
    if v is None:
        return None, "–"
    return v, _s("failed") if v == INF else fmt_ms(v)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _hit_ratio,
             lambda v: v is not None and v >= lab.HIT_MIN, key="hits"),
    GoalSpec("", "during", "", _during, _dups,
             lambda v: v is not None and v < lab.DUP_MAX, settle_extra=0.5, key="dups"),
    GoalSpec("", "after", "", _after, _p99,
             lambda v: v is not None and v < lab.P99_MAX, settle_extra=2.0, key="p99"),
]


class CacheWorld(World):
    id = "caching"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "hit"), (EXTRA1, "shared"), (EXTRA2, "first"),
              (EXTRA3, "dup"), (RED, "rejected"), (LIMIT, "limit", "┄"), (FLUSH_KEY, "flush", "█")]
    chart_top = 600.0
    incident_verbs = ("flush", "end")
    tables = {
        "pages": Table(sort=PAGE_START, times=(PAGE_START, PAGE_END)),
        "reads": Table(sort=READ_START, times=(READ_START, READ_END)),
        "db": Table(sort=DB_QUEUED, times=(DB_QUEUED, DB_START, DB_END)),
    }
    goals = GOALS

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for p in tables["pages"]:
            run.add("served" if p[PAGE_OK] else "failed", p[PAGE_END])
        for r in tables["reads"]:
            run.add("reads", r[READ_START])
            if r[READ_KIND] == HIT:
                run.add("hits", r[READ_START])
        for d in tables["db"]:
            name = "db_rejected" if not d[DB_OK] else "db_dup" if d[DB_DUP] else "db_first"
            run.add(name, d[DB_QUEUED])
            run.add("db", d[DB_QUEUED])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        base = run.count("db", *_before(inc)) / lab.BASELINE_WINDOW
        for s in _seconds(*_during(inc)):
            n = run.count("db", s, s + 1)
            if base and n / base >= 3:
                return [(s + 1.0, self.s("warn_db", ratio=n / base))]
        return []

    def incident_text(self, inc: Incident, start: bool) -> str:
        return self.s("flushed", cause=self.cause(inc))

    def bands(self, variant: str, t: float):
        run = self.runs.get(variant)
        if run is None:
            return []
        return [(i.t0, min(i.t0 + lab.DURING_WINDOW, t), self.band_colour)
                for i in run.incidents if i.t0 <= t]

    def flushed_recently(self, variant: str, t: float) -> bool:
        inc = self.current_incident(variant, t)
        return inc is not None and inc.t0 <= t < inc.t0 + lab.DURING_WINDOW

    def db_state(self, run: Run, t: float) -> tuple[int, int]:
        """(in flight, queued) at time t."""
        active = run.active("db", t, DB_END)
        queued = sum(1 for d in active if d[DB_START] is None or d[DB_START] > t)
        return len(active) - queued, queued

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        recent = run.rows("reads", t - 5, t)
        hits = sum(r[READ_KIND] == HIT for r in recent) / len(recent) if recent else 0.0

        def hit_state(v: float) -> str:
            return "bad" if v < lab.HIT_MIN else "warn" if v < 0.9 else "ok"

        def hit_s(s: int):
            n, h = run.series("reads", s, s + 1)[0], run.series("hits", s, s + 1)[0]
            v = h / n if n else 0.0
            return v, hit_state(v)

        db = run.rows("db", t - 5, t)
        dups = sum(d[DB_DUP] for d in db) / len(db) if db else 0.0

        def dup_state(v: float) -> str:
            return "bad" if v >= lab.DUP_MAX else "ok"

        def dup_s(s: int):
            n, d = run.series("db", s, s + 1)[0], run.series("db_dup", s, s + 1)[0]
            v = d / n if n else 0.0
            return v, dup_state(v)

        span = run.max_dur.get("reads", 0.0)
        ended = [_read_time(r) for r in run.rows("reads", t - 5 - span, t) if t - 5 <= r[READ_END] < t]
        p99 = percentile(ended, 99)

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= 0.05 else "ok"

        def p99_s(s: int):
            # Per-second p99 from raw rows still kept (the tile only shows 30 s).
            times = [_read_time(r) for r in run.rows("reads", s - span, s + 1) if s <= r[READ_END] < s + 1]
            v = percentile(times, 99)
            return (min(v, 1.0) if v is not None else 0.0), p99_state(v)

        tiles = [
            Tile(self.s("tile_hits"), f"{hits:.0%}", "≥80%", hit_state(hits), history(run, t, hit_s)),
            Tile(self.s("tile_dups"), f"{dups:.0%}", "<5%", dup_state(dups), history(run, t, dup_s)),
            Tile(self.s("tile_p99"), self.s("failed") if p99 == INF else fmt_ms(p99), "<100ms", p99_state(p99),
                 history(run, t, p99_s)),
        ]
        last = run.rows("db", t - 1, t)
        first = sum(1 for d in last if d[DB_OK] and not d[DB_DUP])
        dup = sum(1 for d in last if d[DB_OK] and d[DB_DUP])
        rejected = sum(1 for d in last if not d[DB_OK])
        bars = [
            Bar(self.s("bar_users"), [(run.count("reads", t - 1, t), WHITE)]),
            Bar(self.s("bar_db"), [(first, EXTRA2), (dup, EXTRA3), (rejected, RED)]),
        ]
        headline, colour = self._headline(variant, run, t, hits)
        return Traffic(tiles, bars, lab.DB_LIMIT, self.s("limit", limit=lab.DB_LIMIT), headline, colour,
                       title=self.s("toplist"), top=1000.0)

    def _headline(self, variant: str, run: Run, t: float, hits: float):
        inc = self.current_incident(variant, t)
        if inc and inc.t0 <= t < inc.t0 + 10:
            base = run.count("db", *_before(inc)) / lab.BASELINE_WINDOW
            now = run.count("db", t - 1, t)
            if base and now / base >= 1.5:
                return self.s("head_hit_db", ratio=now / base), EXTRA2
            return self.s("head_refilling"), MUTED
        if hits < 0.05:
            return self.s("head_no_cache"), RED
        return self.s("head_cache", share=hits), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("pages", 0.0)
        partial = [p for p in run.rows("pages", s - span - 1, t) if s <= p[PAGE_END] < t]
        served = run.total("served", t) + sum(1 for p in partial if p[PAGE_OK])
        failed = run.total("failed", t) + sum(1 for p in partial if not p[PAGE_OK])
        waiting = len(run.active("pages", t, PAGE_END))
        rspan = run.max_dur.get("reads", 0.0)
        recent = [_read_time(r) for r in run.rows("reads", t - 5 - rspan, t) if t - 5 <= r[READ_END] < t]
        p50, p99 = percentile(recent, 50), percentile(recent, 99)
        # Not request_stats(): the waits here are per read (a page reads 3 keys), and may be "failed".
        words = self.screen.STATS
        return [
            (words["served"], fmt_int(served), GREEN),
            (words["failed"], fmt_int(failed), RED if failed else MUTED),
            (words["waiting"], fmt_int(waiting), EXTRA2 if waiting > 20 else WHITE),
            (words["p50"], self.s("failed") if p50 == INF else fmt_ms(p50), WHITE),
            (words["p99"], self.s("failed") if p99 == INF else fmt_ms(p99), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA2, run.hist.get("db_first", [])), (EXTRA3, run.hist.get("db_dup", [])),
                (RED, run.hist.get("db_rejected", []))]

    def chart_limit(self):
        return lab.DB_LIMIT, f"{lab.DB_LIMIT:.0f}/s"

    def legend_notes(self) -> list[str]:
        return [self.s("note_dots"), self.s("note_chart")]


WORLD = CacheWorld
