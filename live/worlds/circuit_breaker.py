"""World for lab circuit_breaker."""

from __future__ import annotations

from labs.circuit_breaker import lab
from labs.circuit_breaker.scenario import DEPS, FAILED, GAVE_UP, OK, REFUSED
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, RGB, WHITE,
)
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Stage, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

DOWN_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
NAMES = {"payments": "Payments", "recs": "Recs"}

REQ_ID, REQ_START, REQ_GOT, REQ_END, REQ_DEP, REQ_OUTCOME, REQ_CALLED = range(7)
CALL_START, CALL_REQ, CALL_DEP, CALL_END, CALL_OUTCOME = range(5)
WORK_GOT, WORK_REQ, WORK_DEP, WORK_FREED = range(4)


def _sick(inc: Incident) -> int:
    return DEPS.index(inc.kind)


def _served(rows: list[tuple]) -> float | None:
    return sum(r[REQ_OUTCOME] == OK for r in rows) / len(rows) if rows else None


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0 - 2.0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = _served([r for r in run.rows("requests", a, min(b, upto)) if r[REQ_END] <= upto])
    return (None, "–") if v is None else (v, f"{v:.0%}")


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _calls(run: Run, inc: Incident, upto: float):
    """How long calls to the slow dependency take (p99): a timeout bounds it."""
    sick = _sick(inc)
    took = [c[CALL_END] - c[CALL_START] for c in run.rows("calls", inc.t0, min(inc.t1, upto))
            if c[CALL_DEP] == sick and c[CALL_END] <= upto]
    v = percentile(took, 99)
    return (None, "–") if v is None else (v, f"{v:.1f}s")


def _healthy(run: Run, inc: Incident, upto: float):
    sick = _sick(inc)
    v = _served([r for r in run.rows("requests", inc.t0, min(inc.t1, upto))
                 if r[REQ_DEP] != sick and r[REQ_END] <= upto])
    return (None, "–") if v is None else (v, f"{v:.0%}")


def _fast_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 + lab.DETECT, max(inc.t1, inc.t0 + lab.DETECT + 1.0)


def _fast(run: Run, inc: Incident, upto: float):
    """How long users wait on the slow dependency once it is known to be slow (p99)."""
    sick = _sick(inc)
    a, b = _fast_window(inc)
    took = [r[REQ_END] - r[REQ_START] for r in run.rows("requests", a, min(b, upto))
            if r[REQ_DEP] == sick and r[REQ_END] <= upto]
    v = percentile(took, 99)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.AFTER[0], inc.t1 + lab.AFTER[1]


def _back(run: Run, inc: Incident, upto: float):
    sick = _sick(inc)
    a, b = _after(inc)
    v = _served([r for r in run.rows("requests", a, min(b, upto)) if r[REQ_DEP] == sick and r[REQ_END] <= upto])
    return (None, "–") if v is None else (v, f"{v:.0%}")


GOALS = [
    GoalSpec("Baseline ok", "before", "Client must return results",
             _before, _baseline, lambda v: v is not None and v >= lab.BASELINE_MIN),
    GoalSpec("Calls ≤ 1.2s", "during", "time out after TIMEOUT",
             _during, _calls, lambda v: v is not None and v <= lab.CALL_MAX),
    GoalSpec("Healthy ≥ 99%", "during", "a Bulkhead per dependency",
             _during, _healthy, lambda v: v is not None and v >= lab.HEALTHY_MIN),
    GoalSpec("Fail fast <50ms", "during", "a CircuitBreaker per dep",
             _fast_window, _fast, lambda v: v is not None and v < lab.FAST_MAX, settle_extra=2.5),
    GoalSpec("Back ≥ 95%", "after", "close the breaker again",
             _after, _back, lambda v: v is not None and v >= lab.RECOVERED_MIN, settle_extra=2.5),
]


class CircuitBreakerWorld(World):
    id = "circuit_breaker"
    title = "Circuit breaker"
    files = ("labs/circuit_breaker/main.py",)
    view = "lanes"
    stages = [Stage(label, story, colour, nxt) for (label, story, nxt), colour
              in zip(lab.STAGES, (RED, EXTRA2, EXTRA1, BLUE))]
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "fast call"), (EXTRA1, "waits for a worker"),
              (EXTRA2, "slow call"), (EXTRA3, "refused"), (RED, "failed"), (GREEN, "served"),
              (LIMIT, "workers", "┄"), (DOWN_KEY, "incident", "█")]
    incident_name = "Slowdown"
    incident_verbs = ("SLOW", "FAST")
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

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1)):
            busy = sum(run.series(n, s, s + 1)[0] for n in ("busy_ok", "busy_sick"))
            if busy >= self.workers * 0.95:
                return [(s + 1.0, f"all {self.workers} workers are busy")]
        return []

    def incident_title(self, inc: Incident) -> str:
        return f"{NAMES[inc.kind]} slow #{inc.index + 1}"

    def incident_text(self, inc: Incident, start: bool) -> str:
        name = NAMES[inc.kind]
        if start:
            return f"{name} is slow, {inc.severity:.0f} s a call: {inc.cause}"
        return f"{name} is fast again"

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

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
            Tile("Healthy", "–" if served is None else f"{served:.0%}", "≥99%", served_state(served),
                 history(run, t, served_s)),
            Tile("Fails", "–" if fast is None else fmt_ms(fast), "<50ms", fast_state(fast),
                 history(run, t, fast_s)),
            Tile("Workers", f"{busy}/{self.workers}", "busy", busy_state(busy), history(run, t, busy_s)),
        ]
        last = [r for r in run.rows("requests", t - 1 - span, t) if t - 1 <= r[REQ_END] < t]
        bars = []
        for d, name in enumerate(DEPS):
            rows = [r for r in last if r[REQ_DEP] == d]
            count = {k: sum(r[REQ_OUTCOME] == k for r in rows) for k in (OK, REFUSED, FAILED, GAVE_UP)}
            bars.append(Bar(NAMES[name], [(count[OK], WHITE), (count[REFUSED], EXTRA3),
                                          (count[FAILED], EXTRA2), (count[GAVE_UP], RED)]))
        headline, colour = self._headline(variant, run, t, served)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title="Answers",
                       subtitle="per second, last 1 s", top=100.0)

    def _headline(self, variant: str, run: Run, t: float, served: float | None):
        inc = self.incident_at(variant, t)
        if inc is not None:
            healthy = NAMES[DEPS[1 - _sick(inc)]]
            if served is not None and served < lab.HEALTHY_MIN:
                return f"{NAMES[inc.kind]} is slow, and {healthy} fails too", RED
            return f"{NAMES[inc.kind]} is slow; {healthy} is fine", BLUE
        last = self.current_incident(variant, t)
        if last is not None and last.t1 <= t < last.t1 + 10:
            refused = self.door_at(run, t, _sick(last))
            if refused > 0.5:
                return f"{NAMES[last.kind]} is back; the breaker is still open", EXTRA2
            return f"{NAMES[last.kind]} is back", BLUE
        return "Both dependencies answer fast", MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("requests", 0.0)
        partial = [r for r in run.rows("requests", s - span - 1, t) if s <= r[REQ_END] < t]
        served = run.total("served", t) + sum(1 for r in partial if r[REQ_OUTCOME] == OK)
        failed = sum(run.total(n, t) for n in ("failed", "refused", "gave_up")) + sum(
            1 for r in partial if r[REQ_OUTCOME] != OK)
        waiting = len(run.active("requests", t, REQ_END))
        recent = [r[REQ_END] - r[REQ_START] for r in run.rows("requests", t - 5 - span, t)
                  if t - 5 <= r[REQ_END] < t]
        return [
            ("served", fmt_int(served), GREEN),
            ("failed", fmt_int(failed), RED if failed else MUTED),
            ("waiting", fmt_int(waiting), EXTRA2 if waiting > 20 else WHITE),
            ("p50", fmt_ms(percentile(recent, 50)), WHITE),
            ("p99", fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("busy_ok", [])), (EXTRA2, run.hist.get("busy_sick", []))]

    def chart_limit(self):
        return float(self.workers), f"{self.workers} workers"

    def legend_notes(self) -> list[str]:
        return ["The chart: busy workers each second."]


WORLD = CircuitBreakerWorld
