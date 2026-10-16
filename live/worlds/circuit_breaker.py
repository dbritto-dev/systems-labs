"""World for lab circuit_breaker. Its words are in labs/circuit_breaker/text/<lang>.py."""

from __future__ import annotations

from labs.circuit_breaker import lab
from labs.circuit_breaker.scenario import DEPS, FAILED, GAVE_UP, OK, REFUSED
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, RGB, WHITE,
)
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, below,
    fmt_int, fmt_ms, history, percentile, so_far,
)

DOWN_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents

REQ_ID, REQ_START, REQ_GOT, REQ_END, REQ_DEP, REQ_OUTCOME, REQ_CALLED = range(7)
CALL_START, CALL_REQ, CALL_DEP, CALL_END, CALL_OUTCOME = range(5)
WORK_GOT, WORK_REQ, WORK_DEP, WORK_FREED = range(4)


def _sick(inc: Incident) -> int:
    return DEPS.index(inc.kind)


def _served(rows: list[tuple]) -> float | None:
    return sum(r[REQ_OUTCOME] == OK for r in rows) / len(rows) if rows else None


# ---------------------------------------------------------------- goals


_before = baseline_window(lab, gap=2.0)


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = _served([r for r in run.rows("requests", a, min(b, upto)) if r[REQ_END] <= upto])
    return NO_VALUE if v is None else (v, f"{v:.0%}")


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _calls(run: Run, inc: Incident, upto: float):
    """How long calls to the slow dependency take (p99): a timeout bounds it."""
    sick = _sick(inc)
    took = [c[CALL_END] - c[CALL_START] for c in run.rows("calls", inc.t0, min(inc.t1, upto))
            if c[CALL_DEP] == sick and c[CALL_END] <= upto]
    v = percentile(took, 99)
    return NO_VALUE if v is None else (v, f"{v:.1f}s")


def _healthy(run: Run, inc: Incident, upto: float):
    sick = _sick(inc)
    v = _served([r for r in run.rows("requests", inc.t0, min(inc.t1, upto))
                 if r[REQ_DEP] != sick and r[REQ_END] <= upto])
    return NO_VALUE if v is None else (v, f"{v:.0%}")


def _fast_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 + lab.DETECT, max(inc.t1, inc.t0 + lab.DETECT + 1.0)


def _fast(run: Run, inc: Incident, upto: float):
    """How long users wait on the slow dependency once it is known to be slow (p99)."""
    sick = _sick(inc)
    a, b = _fast_window(inc)
    took = [r[REQ_END] - r[REQ_START] for r in run.rows("requests", a, min(b, upto))
            if r[REQ_DEP] == sick and r[REQ_END] <= upto]
    v = percentile(took, 99)
    return NO_VALUE if v is None else (v, fmt_ms(v))


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.AFTER[0], inc.t1 + lab.AFTER[1]


def _back(run: Run, inc: Incident, upto: float):
    sick = _sick(inc)
    a, b = _after(inc)
    v = _served([r for r in run.rows("requests", a, min(b, upto)) if r[REQ_DEP] == sick and r[REQ_END] <= upto])
    return NO_VALUE if v is None else (v, f"{v:.0%}")


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), key="baseline"),
    GoalSpec("", "during", "", _during, _calls, at_most(lab.CALL_MAX), key="calls"),
    GoalSpec("", "during", "", _during, _healthy, at_least(lab.HEALTHY_MIN), key="healthy"),
    GoalSpec("", "during", "", _fast_window, _fast, below(lab.FAST_MAX), settle_extra=2.5, key="fast"),
    GoalSpec("", "after", "", _after, _back, at_least(lab.RECOVERED_MIN), settle_extra=2.5, key="back"),
]


class CircuitBreakerWorld(World):
    id = "circuit_breaker"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, EXTRA1, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "fast_call"), (EXTRA1, "waits_worker"),
              (EXTRA2, "slow_call"), (EXTRA3, "refused"), (RED, "failed"), (GREEN, "served"),
              (LIMIT, "workers", "┄"), (DOWN_KEY, "incident", "█")]
    incident_verbs = ("slow", "fast")
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "calls": Table(sort=CALL_START, times=(CALL_START, CALL_END)),
        "work": Table(sort=WORK_GOT, times=(WORK_GOT, WORK_FREED)),
    }
    goals = GOALS

    @property
    def workers(self) -> int:
        return int(self.params.get("workers", 24))

    @property
    def chart_top(self) -> float:  # type: ignore[override]
        return self.workers * 1.25

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            name = {OK: "served", FAILED: "failed", REFUSED: "refused", GAVE_UP: "gave_up"}[r[REQ_OUTCOME]]
            run.add(name, r[REQ_END])
            run.add("asked", r[REQ_START])
        for w in tables["work"]:  # worker-seconds per second: how many workers were busy
            sick = any(i.t0 <= w[WORK_GOT] < i.t1 and _sick(i) == w[WORK_DEP] for i in run.incidents)
            name = "busy_sick" if sick else "busy_ok"
            a, b = w[WORK_GOT], w[WORK_FREED]
            s = int(a)
            while s < b:
                run.add(name, s, min(b, s + 1) - max(a, s))
                s += 1

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1)):
            busy = sum(run.series(n, s, s + 1)[0] for n in ("busy_ok", "busy_sick"))
            if busy >= self.workers * 0.95:
                return [(s + 1.0, self.s("warn_busy", workers=self.workers))]
        return []

    def dep_name(self, dep: str) -> str:
        """A dependency's name on screen ("payments" -> "Payments" / "Pagos")."""
        return self.s(f"dep_{dep}")

    def incident_title(self, inc: Incident) -> str:
        name = self.s("title", dep=self.dep_name(inc.kind))
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        name = self.dep_name(inc.kind)
        if start:
            return self.s("slow", dep=name, seconds=inc.severity, cause=self.cause(inc))
        return self.s("fast_again", dep=name)

    def busy_at(self, run: Run, t: float) -> int:
        """Workers busy at t (the server side, whether or not the user still waits)."""
        return len(run.active("work", t, WORK_FREED))

    def door_at(self, run: Run, t: float, dep: int) -> float:
        """The share of requests to `dep` that ended in the last second refused without a call."""
        span = run.max_dur.get("requests", 0.0)
        ended = [r for r in run.rows("requests", t - 1 - span, t) if t - 1 <= r[REQ_END] < t and r[REQ_DEP] == dep]
        return sum(r[REQ_OUTCOME] == REFUSED for r in ended) / len(ended) if len(ended) >= 5 else 0.0

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        inc = self.incident_at(variant, t)
        span = run.max_dur.get("requests", 0.0)
        ended = [r for r in run.rows("requests", t - 5 - span, t) if t - 5 <= r[REQ_END] < t]
        healthy = [r for r in ended if inc is None or r[REQ_DEP] != _sick(inc)]
        served = _served(healthy)

        def served_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.HEALTHY_MIN else "ok"

        def served_s(s: int):
            ok = run.series("served", s, s + 1)[0]
            bad = sum(run.series(n, s, s + 1)[0] for n in ("failed", "refused", "gave_up"))
            v = ok / (ok + bad) if ok + bad else 1.0
            return v, "bad" if v < 0.9 else "warn" if v < 0.99 else "ok"

        failed = [r[REQ_END] - r[REQ_START] for r in ended if r[REQ_OUTCOME] != OK]
        fast = percentile(failed, 99)

        def fast_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.FAST_MAX else "ok"

        def fast_s(s: int):
            slow = run.series("failed", s, s + 1)[0] + run.series("gave_up", s, s + 1)[0]
            quick = run.series("refused", s, s + 1)[0]
            return slow + quick, "bad" if slow else "ok" if quick else "idle"

        busy = self.busy_at(run, t)

        def busy_state(n: float) -> str:
            return "bad" if n >= self.workers - 0.5 else "warn" if n >= self.workers * 0.8 else "ok"

        def busy_s(s: int):
            n = run.series("busy_ok", s, s + 1)[0] + run.series("busy_sick", s, s + 1)[0]
            return n, busy_state(n)

        tiles = [
            Tile(self.s("tile_healthy"), "–" if served is None else f"{served:.0%}", "≥99%",
                 served_state(served), history(run, t, served_s)),
            Tile(self.s("tile_fails"), "–" if fast is None else fmt_ms(fast), "<50ms", fast_state(fast),
                 history(run, t, fast_s)),
            Tile(self.s("tile_workers"), f"{busy}/{self.workers}", self.s("target_busy"), busy_state(busy),
                 history(run, t, busy_s)),
        ]
        last = [r for r in run.rows("requests", t - 1 - span, t) if t - 1 <= r[REQ_END] < t]
        bars = []
        for d, name in enumerate(DEPS):
            rows = [r for r in last if r[REQ_DEP] == d]
            count = {k: sum(r[REQ_OUTCOME] == k for r in rows) for k in (OK, REFUSED, FAILED, GAVE_UP)}
            bars.append(Bar(self.dep_name(name), [(count[OK], WHITE), (count[REFUSED], EXTRA3),
                                                  (count[FAILED], EXTRA2), (count[GAVE_UP], RED)]))
        headline, colour = self._headline(variant, run, t, served)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("answers"), top=100.0)

    def _headline(self, variant: str, run: Run, t: float, served: float | None):
        inc = self.incident_at(variant, t)
        if inc is not None:
            sick, healthy = self.dep_name(inc.kind), self.dep_name(DEPS[1 - _sick(inc)])
            if served is not None and served < lab.HEALTHY_MIN:
                return self.s("head_both_fail", dep=sick, healthy=healthy), RED
            return self.s("head_contained", dep=sick, healthy=healthy), BLUE
        last = self.current_incident(variant, t)
        if last is not None and last.t1 <= t < last.t1 + 10:
            refused = self.door_at(run, t, _sick(last))
            if refused > 0.5:
                return self.s("head_still_open", dep=self.dep_name(last.kind)), EXTRA2
            return self.s("head_back", dep=self.dep_name(last.kind)), BLUE
        return self.s("head_calm"), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        span = run.max_dur.get("requests", 0.0)
        served = so_far(run, t, "served", "requests", REQ_END, lambda r: r[REQ_OUTCOME] == OK)
        failed = so_far(run, t, ("failed", "refused", "gave_up"), "requests", REQ_END, lambda r: r[REQ_OUTCOME] != OK)
        waiting = len(run.active("requests", t, REQ_END))
        recent = [r[REQ_END] - r[REQ_START] for r in run.rows("requests", t - 5 - span, t)
                  if t - 5 <= r[REQ_END] < t]
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
        return [(WHITE, run.hist.get("busy_ok", [])), (EXTRA2, run.hist.get("busy_sick", []))]

    def chart_limit(self):
        return float(self.workers), self.s("chart_limit", workers=self.workers)

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = CircuitBreakerWorld
