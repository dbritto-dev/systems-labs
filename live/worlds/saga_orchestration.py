"""World for lab saga_orchestration. Its words are in labs/saga_orchestration/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.saga_orchestration import lab
from labs.saga_orchestration.api import DECLINED, OK
from labs.saga_orchestration.scenario import DONE, ORPHAN, ROLLED_BACK
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history, percentile

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
INF = float("inf")

(ORD_ID, ORD_START, ORD_END, ORD_STATUS, ORD_DONE, ORD_CHARGES, ORD_GAVE_UP, ORD_KNOWN, ORD_CRASHED,
 ORD_DECLINED, ORD_HELD) = range(11)
CALL_START, CALL_ORDER, CALL_SVC, CALL_UNDO, CALL_END, CALL_OUTCOME = range(6)

_s = strings("saga_orchestration")  # one of the lab's STRINGS, for the goal measures below


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.LEAD, inc.t1  # sagas running when it starts are caught in it too


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER


def _ended(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Sagas that started in [a, b) and ended by `upto`."""
    return [o for o in run.rows("orders", a, min(b, upto)) if o[ORD_END] <= upto]


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    b = min(b, upto)
    done = [o for o in run.rows("orders", a - run.max_dur.get("orders", 0.0), b) if a <= o[ORD_END] < b]
    if not done:
        return None, "–"
    v = sum(1 for o in done if o[ORD_STATUS] != ORPHAN) / len(done)
    return v, f"{v:.0%}"


def _rolled(run: Run, inc: Incident, upto: float):
    failed = [o for o in _ended(run, *_during(inc), upto) if o[ORD_GAVE_UP] and not o[ORD_CRASHED]]
    if not failed:
        return None, _s("none")  # no saga gave up: nothing to roll back
    v = sum(1 for o in failed if not o[ORD_KNOWN]) / len(failed)
    return v, f"{v:.0%}"


def _orphans(run: Run, inc: Incident, upto: float):
    sagas = _ended(run, *_during(inc), upto)
    if not sagas:
        return None, "–"
    n = sum(1 for o in sagas if o[ORD_STATUS] == ORPHAN)
    return n, f"{n}"


def _doomed_orphans(run: Run, inc: Incident, upto: float) -> bool:
    return any(o[ORD_STATUS] == ORPHAN for o in _ended(run, *_during(inc), upto))


def _doubles(run: Run, inc: Incident, upto: float):
    sagas = _ended(run, *_during(inc), upto)
    if not sagas:
        return None, "–"
    n = sum(1 for o in sagas if o[ORD_CHARGES] > 1)
    return n, f"{n}"


def _doomed_doubles(run: Run, inc: Incident, upto: float) -> bool:
    return any(o[ORD_CHARGES] > 1 for o in _ended(run, *_during(inc), upto))


def _completed(run: Run, inc: Incident, upto: float):
    could = [o for o in _ended(run, *_during(inc), upto) if not o[ORD_DECLINED]]
    if not could:
        return None, "–"
    v = sum(1 for o in could if o[ORD_DONE]) / len(could)
    return v, f"{v:.0%}"


def _fast(run: Run, inc: Incident, upto: float):
    times = [(o[ORD_END] - o[ORD_START]) if o[ORD_STATUS] != ORPHAN else INF
             for o in _ended(run, *_after(inc), upto)]
    v = percentile(times, 99)
    if v is None:
        return None, "–"
    return v, "∞" if v == INF else f"{v * 1000:.0f}ms" if v < 1 else f"{v:.1f}s"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, key="baseline"),
    GoalSpec("", "during", "", _during, _rolled, lambda v: v is None or v >= 1.0,
             settle_extra=lab.SETTLE, key="rolled"),
    GoalSpec("", "during", "", _during, _orphans, lambda v: v == 0,
             doomed=_doomed_orphans, settle_extra=lab.SETTLE, key="consistent"),
    GoalSpec("", "during", "", _during, _doubles, lambda v: v is None or v == 0,
             doomed=_doomed_doubles, settle_extra=lab.SETTLE, key="once"),
    GoalSpec("", "during", "", _during, _completed,
             lambda v: v is None or v >= lab.COMPLETED_MIN, settle_extra=lab.SETTLE, key="completed"),
    GoalSpec("", "after", "", _after, _fast,
             lambda v: v is not None and v < lab.P99_MAX, settle_extra=lab.SETTLE, key="fast"),
]


class SagaWorld(World):
    id = "saga_orchestration"
    view = "fanout"  # the orchestrator and the three services it calls, each with its own state
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "step"), (EXTRA1, "retry"), (EXTRA2, "undo"),
              (GREEN, "done"), (RED, "orphan"), (LIMIT, "limit", "┄"), (DOWN_KEY, "incident", "█")]
    incident_verbs = ("timeouts", "calm")
    tables = {
        "orders": Table(sort=ORD_START, times=(ORD_START, ORD_END)),
        "calls": Table(sort=CALL_START, times=(CALL_START, CALL_END)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 20.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["orders"]:
            end, status = o[ORD_END], o[ORD_STATUS]
            run.add("orders", o[ORD_START])
            run.add("served" if o[ORD_DONE] else "failed", end)
            run.add(("orphans", "rolled", "done")[status], end)
            if o[ORD_CHARGES] > 1:
                run.add("doubles", end)
            if not o[ORD_DECLINED]:
                run.add("could", end)
                if o[ORD_DONE]:
                    run.add("could_done", end)

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if start:
            return self.word(inc.kind)
        return self.word("back" if inc.kind == "crash" else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", share=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        out = []
        if inc.kind == "oom":
            down = lab.downtime(inc.kind, inc.t0, inc.t1)
            out += [(down[0], self.s("warn_crash")), (down[1], self.s("crash_end"))]
        rows = run.rows("orders", inc.t0 - lab.LEAD, inc.t1)
        orphans = sum(1 for o in rows if o[ORD_STATUS] == ORPHAN)
        doubles = sum(1 for o in rows if o[ORD_CHARGES] > 1)
        if orphans:
            out.append((inc.t1, self.s("warn_orphans", n=orphans)))
        if doubles:
            out.append((inc.t1, self.s("warn_doubles", n=doubles)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def down_at(self, variant: str, t: float) -> bool:
        """Is the orchestrator down (crashed, not back yet) at t?"""
        inc = self.incident_at(variant, t)
        down = lab.downtime(inc.kind, inc.t0, inc.t1) if inc is not None else None
        return down is not None and down[0] <= t < down[1]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = run.max_dur.get("orders", 0.0)
        recent = [o for o in run.rows("orders", t - 10 - span, t) if t - 10 <= o[ORD_END] < t]
        orphans = sum(1 for o in recent if o[ORD_STATUS] == ORPHAN)
        doubles = sum(1 for o in recent if o[ORD_CHARGES] > 1)
        could = [o for o in recent if not o[ORD_DECLINED]]
        done = sum(1 for o in could if o[ORD_DONE]) / len(could) if could else None

        def count_s(name: str):
            def fn(s: int):
                v = run.series(name, s, s + 1)[0]
                return v, "bad" if v else "ok"
            return fn

        def done_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.COMPLETED_MIN else "ok"

        def done_s(s: int):
            n, ok = run.series("could", s, s + 1)[0], run.series("could_done", s, s + 1)[0]
            v = ok / n if n else None
            return (v or 0.0), done_state(v)

        tiles = [
            Tile(self.s("tile_orphans"), str(orphans), "=0", "bad" if orphans else "ok",
                 history(run, t, count_s("orphans"))),
            Tile(self.s("tile_doubles"), str(doubles), "=0", "bad" if doubles else "ok",
                 history(run, t, count_s("doubles"))),
            Tile(self.s("tile_done"), "–" if done is None else f"{done:.0%}", "≥95%", done_state(done),
                 history(run, t, done_s)),
        ]
        cspan = run.max_dur.get("calls", 0.0)
        calls = [c for c in run.rows("calls", t - 1 - cspan, t) if t - 1 <= c[CALL_END] < t]
        steps = [c for c in calls if not c[CALL_UNDO]]
        ok = sum(1 for c in steps if c[CALL_OUTCOME] == OK)
        declined = sum(1 for c in steps if c[CALL_OUTCOME] == DECLINED)
        undos = len(calls) - len(steps)
        ended = [o for o in run.rows("orders", t - 1 - span, t) if t - 1 <= o[ORD_END] < t]
        by = [sum(1 for o in ended if o[ORD_STATUS] == k) for k in (DONE, ROLLED_BACK, ORPHAN)]
        bars = [
            Bar(self.s("bar_steps"), [(float(ok), WHITE), (float(len(steps) - ok - declined), EXTRA1),
                                      (float(declined), MUTED)]),
            Bar(self.s("bar_undos"), [(float(undos), EXTRA2)]),
            Bar(self.s("bar_sagas"), [(float(by[0]), WHITE), (float(by[1]), EXTRA2), (float(by[2]), RED)]),
        ]
        inc = self.incident_at(variant, t)
        if orphans:
            headline, colour = self.s("head_orphans", n=orphans), RED
        elif self.down_at(variant, t):
            headline, colour = self.s("head_down"), RED
        elif inc is not None:
            headline, colour = self.s("head_failing"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=self.rate * 4)

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "orders", ORD_START, ORD_END, ORD_DONE, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("done", [])), (EXTRA2, run.hist.get("rolled", [])),
                (RED, run.hist.get("orphans", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    chart_top = 40.0

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = SagaWorld
