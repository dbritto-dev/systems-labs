"""World for lab autoscaling. Its words are in labs/autoscaling/text/<lang>.py."""

from __future__ import annotations

import math

from labs.autoscaling import lab
from labs.autoscaling.scenario import MAX_INSTANCES, MIN_INSTANCES, SAMPLE
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, PURPLE, RED, RGB, WHITE
from live.worlds.base import (
    Bar,
    GoalSpec,
    Incident,
    Run,
    Settled,
    Table,
    Tile,
    Traffic,
    World,
    fmt_ms,
    history,
    percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_SLOT = range(5)
S_T, S_DEMAND, S_CAPACITY, S_INSTANCES, S_BOOTING, S_WARMING, S_STATES, S_LOADS, S_CPU = range(9)
T_T, T_BEFORE, T_AFTER, T_RPS, T_CPU, T_INFLIGHT, T_BOOTING, T_WARMING = range(8)
INCIDENT_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
WARM_C, WARMING_C, BOOTING_C, SHORT_C = BLUE, PURPLE, EXTRA1, RED  # the fleet, in every picture
WARN_TIMEOUTS = 5  # timeouts in one second that make a warning
STARTS = {"surge": "surge", "drop": "drop", "noisy": "noisy", "cold": "cold"}  # VERBS keys
ENDS = {"surge": "eases", "drop": "back", "noisy": "quiet", "cold": "warm"}


def needed(demand: float) -> int:
    """Instances the traffic needs at the target: the ideal fleet, which follows it exactly."""
    return max(MIN_INSTANCES, math.ceil(demand / lab.TARGET_RPS - 1e-9))


ideal = needed


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Requests that ended in [a, b)."""
    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b]


def flaps(ticks: list[tuple], since: float) -> int:
    """Instances that flapped: a scaling action at or after `since` that undoes an opposite one of the
    FLAP_WINDOW seconds before it (each instance added or removed is undone at most once)."""
    open_moves: list[list[float]] = []  # [t, instances added (+) or removed (-) not undone yet]
    n = 0
    for r in ticks:
        d = r[T_AFTER] - r[T_BEFORE]
        if not d:
            continue
        t, left = r[T_T], abs(d)
        for m in reversed(open_moves):
            if left and t - m[0] < lab.FLAP_WINDOW and m[1] and (m[1] > 0) != (d > 0):
                k = min(left, abs(m[1]))
                left -= k
                m[1] -= k if m[1] > 0 else -k
                if t >= since:
                    n += k
        open_moves.append([t, left if d > 0 else -left])
    return int(n)


# ---------------------------------------------------------------- goals


def _memo(measure):
    """A frame asks for the same goal values several times: remember the last few (a run only grows, so
    its piece count tells an old answer from a new one)."""
    cache: dict[tuple, tuple] = {}

    def cached(run: Run, inc: Incident, upto: float):
        key = (id(run), run.pieces, inc.index, upto)
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[key] = measure(run, inc, upto)
        return cache[key]

    return cached


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    rows = _ended(run, a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(r[REQ_OK] for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


@_memo
def _served(run: Run, inc: Incident, upto: float):
    """The share of the requests started during the incident that were answered (not timed out)."""
    rows = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_END] <= upto]
    if not rows:
        return None, "–"
    v = sum(r[REQ_OK] for r in rows) / len(rows)
    return v, f"{v:.1%}"


@_memo
def _p99(run: Run, inc: Incident, upto: float):
    """p99 latency of the requests started during the incident (still waiting: counted so far)."""
    cut = min(inc.t1 + lab.SETTLE, upto)
    v = percentile([min(r[REQ_END], cut) - r[REQ_START] for r in run.rows("requests", inc.t0, min(inc.t1, upto))],
                   99)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _end(inc: Incident) -> tuple[float, float]:
    return max(inc.t0, inc.t1 - lab.HEADROOM_WINDOW), inc.t1


def _headroom(run: Run, inc: Incident, upto: float):
    """Spare capacity over the traffic in the last HEADROOM_WINDOW s of the incident: serving capacity
    (warming instances count for what they can do) / requests asked - 1."""
    a, b = _end(inc)
    rows = run.rows("samples", a, min(b, upto))
    asked = sum(r[S_DEMAND] for r in rows)
    if not asked:
        return None, "–"
    v = sum(r[S_CAPACITY] for r in rows) / asked - 1
    return v, f"{v:+.0%}"


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER


def _flaps(run: Run, inc: Incident, upto: float):
    """Instances added and removed again (or removed and added again) within FLAP_WINDOW, from the start of
    the incident to AFTER seconds after it."""
    if upto <= inc.t0:
        return None, "–"
    v = flaps(run.rows("ticks", inc.t0 - lab.FLAP_WINDOW, min(inc.t1 + lab.AFTER, upto)), inc.t0)
    return float(v), str(v)


def _flaps_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _flaps(run, inc, upto)
    return v is not None and v > lab.FLAPS_MAX


def _cost(run: Run, inc: Incident, upto: float):
    """Instance-seconds paid for (booting ones too) over the ideal fleet's, from the start of the incident
    to AFTER seconds after it."""
    rows = run.rows("samples", inc.t0, min(inc.t1 + lab.AFTER, upto))
    if not rows:
        return None, "–"
    v = sum(r[S_INSTANCES] for r in rows) / sum(ideal(r[S_DEMAND]) for r in rows) - 1
    return v, f"{v:+.0%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, key="baseline"),
    GoalSpec("", "during", "", _during, _served,
             lambda v: v is not None and v >= lab.SERVED_MIN, settle_extra=lab.SETTLE, key="served"),
    GoalSpec("", "during", "", _during, _p99,
             lambda v: v is not None and v < lab.P99_MAX, settle_extra=lab.SETTLE, key="p99"),
    GoalSpec("", "during", "", _end, _headroom,
             lambda v: v is not None and v >= lab.HEADROOM_MIN, key="headroom"),
    GoalSpec("", "after", "", _after, _flaps,
             lambda v: v is not None and v <= lab.FLAPS_MAX, doomed=_flaps_doomed, key="flaps"),
    GoalSpec("", "after", "", _after, _cost,
             lambda v: v is not None and v <= lab.COST_MAX, key="cost"),
]


class AutoscalingWorld(World):
    id = "autoscaling"
    view = "lanes"  # the users' view first: does the fleet keep up with them?
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "request"), ([EXTRA1, EXTRA2, EXTRA3], "waits", "●"),
              (GREEN, "served"), (RED, "failed"), (WARM_C, "warm", "◉"), (WARMING_C, "warming", "◉"),
              (BOOTING_C, "booting", "◉"), (SHORT_C, "short", "█"), (LIMIT, "max", "┄"),
              (INCIDENT_KEY, "incident", "█")]
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "samples": Table(sort=S_T, times=(S_T,)),
        "ticks": Table(sort=T_T, times=(T_T,)),
    }
    goals = GOALS
    chart_top = 20.0

    # ---------------------------------------------------------------- incidents

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word((STARTS if start else ENDS).get(inc.kind, "surge"))

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(inc.kind), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        sev = inc.severity
        return self.s(f"{inc.kind}_start", times=sev, share=sev, cpu=sev, cause=self.cause(inc))

    def incident_at(self, run: Run, t: float) -> Incident | None:
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    # ---------------------------------------------------------------- data

    def sample_at(self, run: Run, t: float) -> tuple | None:
        """The fleet at t: the last sample at or before it."""
        rows = run.rows("samples", t - 2 * SAMPLE, t + 1e-9)
        return rows[-1] if rows else None

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("ask", r[REQ_START])
            run.add("served" if r[REQ_OK] else "failed", r[REQ_END])
        for s in tables["samples"]:
            t, warming, booting = s[S_T], s[S_WARMING], s[S_BOOTING]
            warm = s[S_INSTANCES] - warming - booting
            run.add("warm", t, warm * SAMPLE)
            run.add("warming", t, warming * SAMPLE)
            run.add("booting", t, booting * SAMPLE)
            run.add("short", t, max(0.0, ideal(s[S_DEMAND]) - s[S_INSTANCES]) * SAMPLE)
            run.add("fleet", t, s[S_INSTANCES] * SAMPLE)
            run.add("ideal", t, ideal(s[S_DEMAND]) * SAMPLE)
            run.add("demand", t, s[S_DEMAND] * SAMPLE)
            run.add("capacity", t, s[S_CAPACITY] * SAMPLE)
        for r in tables["ticks"]:
            d = r[T_AFTER] - r[T_BEFORE]
            if d:
                run.add("actions", r[T_T])
                run.add("out" if d > 0 else "in", r[T_T], abs(d))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        inc = run.incidents[0]
        scaled_out = sum(run.series("out", int(inc.t0), int(inc.t1) + 1)) > 0
        return lab.stage_of(scaled_out, *(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        out = []
        for s in range(int(inc.t0), int(inc.t1) + 1):
            failed = run.series("failed", s, s + 1)[0]
            if failed >= WARN_TIMEOUTS:
                out.append((s + 1.0, self.s("warn_timeouts", n=failed)))
                break
        ticks = run.rows("ticks", inc.t0 - lab.FLAP_WINDOW, inc.t1 + 1.0)
        for r in ticks:
            if r[T_T] >= inc.t0 and flaps([x for x in ticks if x[T_T] <= r[T_T]], r[T_T]):
                out.append((r[T_T], self.s("warn_flap", n=flaps([x for x in ticks if x[T_T] <= r[T_T]],
                                                                r[T_T]))))
                break
        return out

    # ---------------------------------------------------------------- panel

    def _ratio(self, run: Run, a: int, b: int, top: str, bottom: str) -> float | None:
        x, y = sum(run.series(top, a, b)), sum(run.series(bottom, a, b))
        return x / y if y else None

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        s = int(t)

        def head_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.HEADROOM_MIN else "warn" if v < 0.7 else "ok"

        def head_s(sec: int):
            v = self._ratio(run, sec, sec + 1, "capacity", "demand")
            return (max(0.0, v - 1) if v is not None else 0.0), head_state(None if v is None else v - 1)

        h = self._ratio(run, s - 5, s, "capacity", "demand")
        headroom = None if h is None else h - 1

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.P99_MAX / 2 else "ok"

        def p99_s(sec: int):
            v = percentile([r[REQ_END] - r[REQ_START] for r in _ended(run, sec, sec + 1)], 99)
            return (v or 0.0), p99_state(v)

        p99 = percentile([r[REQ_END] - r[REQ_START] for r in _ended(run, t - 5, t)], 99)

        def cost_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.COST_MAX else "warn" if v > lab.COST_MAX / 2 else "ok"

        def cost_s(sec: int):
            v = self._ratio(run, sec, sec + 1, "fleet", "ideal")
            return (max(0.0, v - 1) if v is not None else 0.0), cost_state(None if v is None else v - 1)

        c = self._ratio(run, s - 60, s, "fleet", "ideal")
        cost = None if c is None else c - 1
        tiles = [
            Tile(self.s("tile_headroom"), "–" if headroom is None else f"{headroom:+.0%}", f"≥{lab.HEADROOM_MIN:.0%}",
                 head_state(headroom), history(run, t, head_s)),
            Tile(self.screen.STATS["p99"], fmt_ms(p99), f"<{fmt_ms(lab.P99_MAX)}", p99_state(p99),
                 history(run, t, p99_s)),
            Tile(self.s("tile_cost"), "–" if cost is None else f"{cost:+.0%}", f"≤+{lab.COST_MAX:.0%}",
                 cost_state(cost), history(run, t, cost_s)),
        ]

        now = self.sample_at(run, t)
        n = booting = warming = need = 0
        if now is not None:
            n, booting, warming = now[S_INSTANCES], now[S_BOOTING], now[S_WARMING]
            demand = sum(run.series("demand", s - 5, s)) / 5 if s >= 5 else now[S_DEMAND]
            need = needed(demand)
        actions = sum(run.series("actions", s - 600, s + 1))
        bars = [
            Bar(self.s("bar_fleet"), [(n - warming - booting, WARM_C), (warming, WARMING_C), (booting, BOOTING_C)]),
            Bar(self.s("bar_needed"), [(need, WHITE)]),
            Bar(self.s("bar_actions"), [(actions, MUTED)]),
        ]
        headline, colour = self._headline(run, t, n, booting, need)
        return Traffic(tiles, bars, MAX_INSTANCES, self.s("limit_max", n=MAX_INSTANCES), headline, colour,
                       title=self.s("toplist"), subtitle=self.s("toplist_sub"), top=MAX_INSTANCES * 1.1, unit="")

    def _headline(self, run: Run, t: float, n: int, booting: int, need: int) -> tuple[str, RGB]:
        s = int(t)
        failed = run.series("failed", s - 1, s)[0]
        if failed:
            return self.s("head_timeouts", n=int(failed)), RED
        flapped = flaps(run.rows("ticks", t - 2 * lab.FLAP_WINDOW, t + 1e-9), t - lab.FLAP_WINDOW)
        if flapped:
            return self.s("head_flapping", n=flapped), EXTRA2
        inc = self.incident_at(run, t)
        last = run.rows("ticks", t - 15, t + 1e-9)
        if inc is not None and inc.kind == "noisy" and last and last[-1][T_CPU] >= 0.7:
            return self.s("head_noisy", cpu=last[-1][T_CPU]), PURPLE
        if n < need:
            if booting:
                return self.s("head_booting", n=booting), BOOTING_C
            return self.s("head_short", need=need, n=n), EXTRA2
        if n > need * (1 + lab.COST_MAX):
            return self.s("head_waste", need=need, n=n), EXTRA2
        return self.s("head_fits", n=n, need=need), BLUE

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "requests", REQ_START, REQ_END, REQ_OK, t, busy=60)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WARM_C, run.hist.get("warm", [])), (WARMING_C, run.hist.get("warming", [])),
                (BOOTING_C, run.hist.get("booting", [])), (SHORT_C, run.hist.get("short", []))]

    def chart_limit(self):
        return float(MAX_INSTANCES), self.s("limit_max", n=MAX_INSTANCES)

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = AutoscalingWorld
