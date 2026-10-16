"""World for lab optimistic_locking. Its words are in labs/optimistic_locking/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.optimistic_locking import lab
from labs.optimistic_locking.api import CLOBBER, COMMIT, CONFLICT as W_CONFLICT
from labs.optimistic_locking.scenario import CONFLICT, ERROR, OK, TIMEOUT_
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE,
)
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, below,
    history, percentile,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_OUTCOME, REQ_TRIES, REQ_LOST, REQ_APP, REQ_BATCH, REQ_HOT = range(10)
W_START, W_REQ, W_N, W_END, W_RESULT, W_APP = range(6)

_s = strings("optimistic_locking")  # one of the lab's STRINGS, for the goal measures below


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _ended(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Requests that started in [a, b) and finished by `upto`."""
    return [r for r in run.rows("requests", a, min(b, upto)) if r[REQ_END] <= upto]


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    b = min(b, upto)
    done = [r for r in run.rows("requests", a - run.max_dur.get("requests", 0.0), b) if a <= r[REQ_END] < b]
    if not done:
        return NO_VALUE
    v = sum(r[REQ_OUTCOME] == OK for r in done) / len(done)
    return v, f"{v:.0%}"


def _lost(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_during(inc), upto)
    if not done:
        return NO_VALUE
    n = sum(r[REQ_LOST] for r in done)
    return n, _s("count", n=n)


def _doomed_lost(run: Run, inc: Incident, upto: float) -> bool:
    return any(r[REQ_LOST] for r in _ended(run, *_during(inc), upto))


def _conflicts(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_during(inc), upto)
    if not done:
        return NO_VALUE
    v = sum(r[REQ_OUTCOME] == CONFLICT for r in done) / len(done)
    return v, f"{v:.1%}"


def _fast(run: Run, inc: Incident, upto: float):
    v = percentile([r[REQ_END] - r[REQ_START] for r in _ended(run, *_during(inc), upto)], 99)
    if v is None:
        return NO_VALUE
    return v, f"{v * 1000:.0f}ms"


def _served(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_during(inc), upto)
    if not done:
        return NO_VALUE
    v = sum(r[REQ_OUTCOME] == OK for r in done) / len(done)
    return v, f"{v:.1%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), key="baseline"),
    GoalSpec("", "during", "", _during, _lost, lambda v: v == 0,
             doomed=_doomed_lost, settle_extra=lab.SETTLE, key="lost"),
    GoalSpec("", "during", "", _during, _conflicts,
             at_most(lab.CONFLICT_MAX), settle_extra=lab.SETTLE, key="conflicts"),
    GoalSpec("", "during", "", _during, _fast, below(lab.P99_MAX), settle_extra=lab.SETTLE, key="fast"),
    GoalSpec("", "during", "", _during, _served, at_least(lab.SERVED_MIN), settle_extra=lab.SETTLE, key="served"),
]


class OptimisticLockingWorld(World):
    id = "optimistic_locking"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first_try"), ([EXTRA1, EXTRA2, EXTRA3], "retries"),
              (EXTRA2, "conflict"), (RED, "lost"), (GREEN, "served"), (LIMIT, "limit", "┄"),
              (DOWN_KEY, "incident", "█")]
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "writes": Table(sort=W_START, times=(W_START, W_END)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 50.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("asks", r[REQ_START])
            run.add("served" if r[REQ_OK] else "failed", r[REQ_END])
            if r[REQ_OUTCOME] == CONFLICT:
                run.add("conflicted", r[REQ_END])
            if r[REQ_TRIES] > 1:
                run.add("retried", r[REQ_START])
            if r[REQ_LOST]:
                run.add("lost", r[REQ_END], r[REQ_LOST])
        names = {COMMIT: "commits", W_CONFLICT: "stale", CLOBBER: "clobbers"}
        for w in tables["writes"]:
            run.add(names[w[W_RESULT]], w[W_END])

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", times=inc.severity, rate=inc.severity, ms=inc.severity * 1000,
                      cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        n = sum(r[REQ_LOST] for r in run.rows("requests", inc.t0, inc.t1))
        return [(inc.t1, self.s("warn_lost", n=n))] if n else []

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = run.max_dur.get("requests", 0.0)
        recent = [r for r in run.rows("requests", t - 10 - span, t) if t - 10 <= r[REQ_END] < t]
        lost = sum(r[REQ_LOST] for r in recent)
        conflicts = sum(1 for r in recent if r[REQ_OUTCOME] == CONFLICT)
        share = conflicts / len(recent) if recent else 0.0
        retried = sum(1 for r in recent if r[REQ_TRIES] > 1) / len(recent) if recent else 0.0

        def lost_s(s: int):
            v = run.series("lost", s, s + 1)[0]
            return v, "bad" if v else "ok"

        def conflict_state(v: float) -> str:
            return "bad" if v > lab.CONFLICT_MAX else "warn" if v > 0 else "ok"

        def conflict_s(s: int):
            n, c = run.series("asks", s, s + 1)[0], run.series("conflicted", s, s + 1)[0]
            v = c / n if n else 0.0
            return v, conflict_state(v)

        def retried_state(v: float) -> str:
            return "warn" if v > 0.1 else "ok"

        def retried_s(s: int):
            n, r = run.series("asks", s, s + 1)[0], run.series("retried", s, s + 1)[0]
            v = r / n if n else 0.0
            return v, retried_state(v)

        tiles = [
            Tile(self.s("tile_lost"), f"{lost:.0f}", "=0", "bad" if lost else "ok", history(run, t, lost_s)),
            Tile(self.s("tile_conflicts"), f"{share:.0%}" if share >= 0.01 or not share else "<1%", "≤1%",
                 conflict_state(share), history(run, t, conflict_s)),
            Tile(self.s("tile_retried"), f"{retried:.0%}", "", retried_state(retried), history(run, t, retried_s)),
        ]
        ended = [r for r in run.rows("requests", t - 1 - span, t) if t - 1 <= r[REQ_END] < t]
        outcomes = [0, 0, 0, 0]
        for r in ended:
            outcomes[r[REQ_OUTCOME]] += 1
        last = run.rows("writes", t - 1 - run.max_dur.get("writes", 0.0), t)
        last = [w for w in last if t - 1 <= w[W_END] < t]
        first, retries, results = 0, 0, [0, 0, 0]
        for w in last:
            results[w[W_RESULT]] += 1
            if w[W_RESULT] == COMMIT:
                first, retries = first + (w[W_N] == 0), retries + (w[W_N] > 0)
        bars = [
            Bar(self.s("bar_users"), [(float(outcomes[OK]), GREEN), (float(outcomes[CONFLICT]), EXTRA2),
                                      (float(outcomes[TIMEOUT_] + outcomes[ERROR]), MUTED)]),
            Bar(self.s("bar_writes"), [(float(first), WHITE), (float(retries), EXTRA1),
                                       (float(results[W_CONFLICT]), EXTRA2), (float(results[CLOBBER]), RED)]),
        ]
        inc = self.incident_at(variant, t)
        if lost:
            headline, colour = self.s("head_lost", n=lost), RED
        elif conflicts:
            headline, colour = self.s("head_conflicts", n=conflicts), EXTRA2
        elif inc is not None:
            headline, colour = self.s(f"head_{inc.kind}"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=self.rate * 4)

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "requests", REQ_START, REQ_END, REQ_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("commits", [])), (EXTRA2, run.hist.get("stale", [])),
                (RED, run.hist.get("clobbers", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    chart_top = 200.0

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = OptimisticLockingWorld
