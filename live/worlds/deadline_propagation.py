"""World for lab deadline_propagation. Its words are in labs/deadline_propagation/text/<lang>.py."""

from __future__ import annotations

from labs.deadline_propagation import lab
import math

from labs.deadline_propagation.scenario import FAILED, GAVE_UP, HOPS, OK, WORK
from live.canvas import BLUE, EXTRA2, GREEN, IDLE_DOT, MUTED, RED, RGB, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, fmt_int,
    fmt_ms, history, percentile, so_far,
)

DOWN_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
DB = len(HOPS) - 1

REQ_ID, REQ_START, REQ_END, REQ_OUTCOME = range(4)
W_ARRIVED, W_REQ, W_HOP, W_GOT, W_FREED, W_GONE, W_BEGAN, W_DONE = range(8)
C_START, C_REQ, C_HOP, C_END, C_OUTCOME, C_GONE = range(6)


def wasted(w: tuple) -> float:
    """Seconds of a row's own work done after its user had left."""
    if w[W_DONE] is None or w[W_GONE] is None:
        return 0.0
    return max(0.0, w[W_DONE] - max(w[W_BEGAN], w[W_GONE]))


def worked(w: tuple) -> float:
    return 0.0 if w[W_DONE] is None else w[W_DONE] - w[W_BEGAN]


def overrun(c: tuple) -> float:
    """How long a caller kept waiting on a call after its user had left."""
    return 0.0 if c[C_GONE] is None else max(0.0, c[C_END] - c[C_GONE])


def left_by(w: tuple, t: float) -> bool:
    """Had this row's user left by t?"""
    return w[W_GONE] is not None and w[W_GONE] <= t


def _served(rows: list[tuple]) -> float | None:
    return sum(r[REQ_OUTCOME] == OK for r in rows) / len(rows) if rows else None


def _waste_of(rows: list[tuple]) -> float | None:
    total = sum(worked(w) for w in rows)
    return sum(wasted(w) for w in rows) / total if total > 0 else None


# ---------------------------------------------------------------- goals


_before = baseline_window(lab, gap=2.0)


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = _served([r for r in run.rows("requests", a, min(b, upto)) if r[REQ_END] <= upto])
    return NO_VALUE if v is None else (v, f"{v:.0%}")


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _busy(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.TAIL


def _waste(run: Run, inc: Incident, upto: float):
    """The share of the services' own work (the db's queries, mostly) done for users who had left."""
    a, b = _busy(inc)
    v = _waste_of([w for w in run.rows("work", a, min(b, upto)) if w[W_FREED] <= upto])
    return NO_VALUE if v is None else (v, f"{v:.0%}")


def capacity_at(run: Run, connections: int, t: float) -> float:
    """Requests a second the db can answer at t: its connections over the time a query takes."""
    for inc in reversed(run.incidents):
        if inc.t0 <= t < inc.t1:
            return connections / inc.severity
    return connections / WORK[DB]


def served_share(run: Run, connections: int, a: float, b: float) -> float | None:
    """Requests served in [a, b) vs what was possible: what the db could do, or what users asked
    if that was less. Whole seconds, so both sides count the same time."""
    a, b = float(math.ceil(a)), float(math.floor(b))
    if b - a < 1.0:
        return None
    possible = sum(min(run.series("asked", s, s + 1)[0], capacity_at(run, connections, s + 0.5))
                   for s in range(int(a), int(b)))
    span = run.max_dur.get("requests", 0.0)
    got = sum(1 for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b and r[REQ_OUTCOME] == OK)
    return min(1.0, got / possible) if possible else None


def _served_during(run: Run, inc: Incident, upto: float):
    a, b = _during(inc)
    v = served_share(run, run.data.get("connections", 3), a, min(b, upto))
    return NO_VALUE if v is None else (v, f"{v:.0%}")


def _overrun(run: Run, inc: Incident, upto: float):
    """How long callers kept waiting after their user had left (p99 of every call)."""
    a, b = _during(inc)
    v = percentile([overrun(c) for c in run.rows("calls", a, min(b, upto)) if c[C_END] <= upto], 99)
    return NO_VALUE if v is None else (v, fmt_ms(v) if v > 0 else "0ms")


def _overrun_doomed(run: Run, inc: Incident, upto: float) -> bool:
    """More calls overran already than 1% of all the calls the incident will see: it cannot pass."""
    a, b = _during(inc)
    seen = min(b, upto) - a
    if seen < 2.0:
        return False
    calls = [c for c in run.rows("calls", a, min(b, upto)) if c[C_END] <= upto]
    late = sum(overrun(c) > lab.OVERRUN_MAX for c in calls)
    return late > 0.02 * len(calls) * (b - a) / seen  # twice what would fail, so an alert is never wrong


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), key="baseline"),
    GoalSpec("", "during", "", _busy, _waste, at_most(lab.WASTE_MAX), settle_extra=3.0, key="waste"),
    GoalSpec("", "during", "", _during, _served_during, at_least(lab.SERVED_MIN), settle_extra=2.5, key="served"),
    GoalSpec("", "during", "", _during, _overrun, at_most(lab.OVERRUN_MAX), doomed=_overrun_doomed, settle_extra=3.0,
             key="overrun"),
]


def _spread(run: Run, name: str, a: float, b: float) -> None:
    """Add the seconds of [a, b) to the history `name`, second by second."""
    s = int(a)
    while s < b:
        run.add(name, s, min(b, s + 1) - max(a, s))
        s += 1


class DeadlinePropagationWorld(World):
    id = "deadline_propagation"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "waiting"), (EXTRA2, "waiting_long"), (GREEN, "served"),
              (RED, "failed"), (RED, "abandoned", "○"), (DOWN_KEY, "incident", "█")]
    incident_verbs = ("slow", "fast")
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "work": Table(sort=W_ARRIVED, times=(W_ARRIVED, W_FREED)),
        "calls": Table(sort=C_START, times=(C_START, C_END)),
    }
    goals = GOALS

    @property
    def connections(self) -> int:
        return int(self.params.get("connections", 3))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        run.data["connections"] = self.connections
        for r in tables["requests"]:
            name = {OK: "served", FAILED: "failed", GAVE_UP: "gave_up"}[r[REQ_OUTCOME]]
            run.add(name, r[REQ_END])
            run.add("asked", r[REQ_START])
        for w in tables["work"]:
            if w[W_DONE] is None:
                continue
            cut = w[W_DONE] if w[W_GONE] is None else min(w[W_DONE], max(w[W_BEGAN], w[W_GONE]))
            _spread(run, "work_live", w[W_BEGAN], cut)
            _spread(run, "work_waste", cut, w[W_DONE])
            if w[W_HOP] == DB:  # a query: for a user still waiting when it started, or for nobody
                run.add("q_dead" if left_by(w, w[W_BEGAN]) else "q_live", w[W_DONE])
        for c in tables["calls"]:
            run.add("calls", c[C_END])
            if overrun(c) > lab.OVERRUN_MAX:
                run.add("overran", c[C_END])

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1 + lab.TAIL)):
            live, dead = run.series("q_live", s, s + 1)[0], run.series("q_dead", s, s + 1)[0]
            if dead >= 5 and dead >= live:
                return [(s + 1.0, self.s("warn_waste"))]
        return []

    def hop_name(self, hop: int) -> str:
        return self.s(f"hop_{HOPS[hop]}")

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s("title"), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if start:
            return self.s("slow", ms=inc.severity * 1000, cause=self.cause(inc))
        return self.s("fast_again")

    def at_hops(self, run: Run, t: float) -> list[tuple[int, int, int]]:
        """Per service at t: (requests it is working on for a waiting user, queued for a worker,
        for a user who has left: queued, working or waiting on the next service)."""
        out = [[0, 0, 0] for _ in HOPS]
        for w in run.active("work", t, W_FREED):
            if left_by(w, t):
                out[w[W_HOP]][2] += 1
            elif w[W_GOT] > t:
                out[w[W_HOP]][1] += 1
            elif w[W_DONE] is not None and w[W_BEGAN] <= t < w[W_DONE]:
                out[w[W_HOP]][0] += 1
        return [tuple(x) for x in out]  # type: ignore[misc]

    def db_busy(self, run: Run, t: float) -> tuple[int, int]:
        """The db's connections running a query at t: (for waiting users, for users who left)."""
        live = dead = 0
        for w in run.active("work", t, W_FREED):
            if w[W_HOP] == DB and w[W_DONE] is not None and w[W_BEGAN] <= t < w[W_DONE]:
                if left_by(w, t):
                    dead += 1
                else:
                    live += 1
        return live, dead

    # ---------------------------------------------------------------- panel

    def _recent(self, run: Run, table: str, end_col: int, t: float, span: float = 5.0) -> list[tuple]:
        longest = run.max_dur.get(table, 0.0)
        return [r for r in run.rows(table, t - span - longest, t) if t - span <= r[end_col] < t]

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        waste = _waste_of(self._recent(run, "work", W_FREED, t))
        served = served_share(run, self.connections, t - 5.0, t)
        over = percentile([overrun(c) for c in self._recent(run, "calls", C_END, t)], 99)

        def waste_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.WASTE_MAX else "warn" if v > 0.01 else "ok"

        def waste_s(s: int):
            live, dead = run.series("work_live", s, s + 1)[0], run.series("work_waste", s, s + 1)[0]
            v = dead / (live + dead) if live + dead else 0.0
            return v, waste_state(v)

        def served_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.SERVED_MIN else "warn" if v < 0.95 else "ok"

        def served_s(s: int):
            v = served_share(run, self.connections, s, s + 1)
            return (1.0, "idle") if v is None else (v, served_state(v))

        def over_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.OVERRUN_MAX else "ok"

        def over_s(s: int):
            n = run.series("overran", s, s + 1)[0]
            return n, "bad" if n else "ok"

        tiles = [
            Tile(self.s("tile_waste"), "–" if waste is None else f"{waste:.0%}", "≤5%", waste_state(waste),
                 history(run, t, waste_s)),
            Tile(self.s("tile_served"), "–" if served is None else f"{served:.0%}", "≥80%",
                 served_state(served), history(run, t, served_s)),
            Tile(self.s("tile_overrun"), "–" if over is None else fmt_ms(over) if over > 0 else "0ms", "<10ms",
                 over_state(over), history(run, t, over_s)),
        ]
        bars = []
        for k, (live, queued, dead) in enumerate(self.at_hops(run, t)):
            bars.append(Bar(self.hop_name(k), [(live, WHITE), (queued, EXTRA2), (dead, RED)]))
        headline, colour = self._headline(variant, run, t)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("at_hops"),
                       subtitle=self.s("at_hops_sub"), unit="")

    def _headline(self, variant: str, run: Run, t: float):
        inc = self.incident_at(variant, t)
        live, dead = self.db_busy(run, t)
        if inc is not None:
            if dead:
                return self.s("head_waste"), RED
            return self.s("head_slow"), BLUE
        last = self.current_incident(variant, t)
        if last is not None and last.t1 <= t < last.t1 + 10:
            if dead:
                return self.s("head_backlog"), EXTRA2
            return self.s("head_back"), BLUE
        return self.s("head_calm"), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        served = so_far(run, t, "served", "requests", REQ_END, lambda r: r[REQ_OUTCOME] == OK)
        failed = so_far(run, t, ("failed", "gave_up"), "requests", REQ_END, lambda r: r[REQ_OUTCOME] != OK)
        waiting = len(run.active("requests", t, REQ_END))
        recent = [r[REQ_END] - r[REQ_START] for r in self._recent(run, "requests", REQ_END, t)]
        words = self.screen.STATS
        return [
            (words["served"], fmt_int(served), GREEN),
            (words["failed"], fmt_int(failed), RED if failed else MUTED),
            (words["waiting"], fmt_int(waiting), EXTRA2 if waiting > 20 else WHITE),
            (words["p50"], fmt_ms(percentile(recent, 50)), WHITE),
            (words["p99"], fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("q_live", [])), (RED, run.hist.get("q_dead", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = DeadlinePropagationWorld
