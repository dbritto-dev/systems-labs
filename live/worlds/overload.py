"""World for lab overload. Its words are in labs/overload/text/<lang>.py."""

from __future__ import annotations

import math
from bisect import bisect_right

from core.i18n import strings
from labs.overload import lab
from labs.overload.scenario import FAILED, GAVE_UP, IN_TIME, LATE, OK, REFUSED, REJECTED, SERVED
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, fmt_ms, history, percentile,
)

REQ_CLIENT, REQ_FIRST, REQ_DONE, REQ_OUTCOME, REQ_TRIES = range(5)
TRY_SENT, TRY_ID, TRY_CLIENT, TRY_ATTEMPT, TRY_END, TRY_RESULT = range(6)
WORK_START, WORK_ID, WORK_END, WORK_KIND = range(4)
Q_T, Q_LEN, Q_STALE = range(3)

TRIES = (WHITE, EXTRA1, EXTRA2)  # first try, retry 1, retry 2
WASTED = EXTRA3  # work done for a user who already left
INCIDENT_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents


_s = strings("overload")  # one of the lab's STRINGS, for the goal measures below


def capacity_at(run: Run, t: float) -> float:
    """Requests/s the server can do at t (less during a capacity drop)."""
    for inc in reversed(run.incidents):
        if inc.t0 <= t < inc.t1:
            return lab.CAPACITY * (inc.severity if inc.kind == "capacity" else 1.0)
    return lab.CAPACITY


def _seconds(a: float, b: float) -> range:
    return range(int(a), int(b))


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0 - 1.0  # the last second's answers come after t0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    firsts = [r for r in run.rows("tries", a, min(b, upto)) if r[TRY_ATTEMPT] == 0 and r[TRY_END] <= upto]
    if not firsts:
        return None, "–"
    v = sum(r[TRY_RESULT] == OK for r in firsts) / len(firsts)
    return v, f"{v:.0%}"


def _busy(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _queue(run: Run, inc: Incident, upto: float):
    a, b = _busy(inc)
    longest = max((q[Q_LEN] for q in run.rows("queue", a, min(b, upto))), default=None)
    return (None, "–") if longest is None else (float(longest), fmt_int(longest))


def _queue_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _queue(run, inc, upto)
    return v is not None and v > lab.QUEUE_MAX


def _waste(run: Run, inc: Incident, upto: float):
    a, b = _busy(inc)
    work = [w for w in run.rows("work", a, min(b, upto)) if w[WORK_KIND] != 2]
    if not work:
        return None, "–"
    v = sum(w[WORK_KIND] == LATE for w in work) / len(work)
    return v, f"{v:.0%}"


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, max(inc.t1, inc.t0 + 1.0)


def _in_time(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Tries answered in time within [a, b) (they were sent up to 1 s before)."""
    return [r for r in run.rows("tries", a - 1.0, min(b, upto))
            if r[TRY_RESULT] == OK and a <= r[TRY_END] < min(b, upto)]


def _goodput(run: Run, inc: Incident, upto: float):
    """Replies in time vs what was possible: the server's capacity, or what users asked if less.
    Whole seconds inside the incident, so both sides count the same time."""
    a, b = _during(inc)
    a, b = float(math.ceil(a)), float(math.floor(min(b, upto)))
    if b - a < 1.0:
        return None, "–"
    possible = 0.0
    for s in _seconds(a, b):
        asked = sum(1 for r in run.rows("tries", s, s + 1) if r[TRY_ATTEMPT] == 0)
        possible += min(capacity_at(run, s + 0.5), asked)
    got = len(_in_time(run, a, b, upto))
    if not possible:
        return None, "–"
    v = got / possible
    return v, f"{v:.0%}"


def _fast(run: Run, inc: Incident, upto: float):
    a, b = _during(inc)
    waits = [r[TRY_END] - r[TRY_SENT] for r in _in_time(run, a, b, upto)]
    v = percentile(waits, 50)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.RECOVERY + lab.RECOVERY_RUN + 1.5


def _first_ok(run: Run, s: int, upto: float) -> float | None:
    firsts = [r for r in run.rows("tries", s, s + 1) if r[TRY_ATTEMPT] == 0 and r[TRY_END] <= upto]
    return sum(r[TRY_RESULT] == OK for r in firsts) / len(firsts) if firsts else None


def _recovered(run: Run, inc: Incident, upto: float):
    """Seconds after the incident until first tries are answered in time again (3 s in a row)."""
    start = int(inc.t1)
    for s in range(start, int(inc.t1 + lab.RECOVERY) + 1):
        shares = [_first_ok(run, x, upto) for x in range(s, s + lab.RECOVERY_RUN)]
        if any(v is None for v in shares):
            return None, "–"  # not known yet
        if all(v >= lab.RECOVERED_MIN for v in shares):
            v = max(0.0, s - inc.t1)
            return v, _s("seconds", seconds=v)
    return float("inf"), _s("over_seconds", seconds=lab.RECOVERY)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, key="baseline"),
    GoalSpec("", "during", "", _busy, _queue,
             lambda v: v is not None and v <= lab.QUEUE_MAX, doomed=_queue_doomed, key="queue"),
    GoalSpec("", "during", "", _busy, _waste,
             lambda v: v is not None and v < lab.WASTE_MAX, key="waste"),
    GoalSpec("", "during", "", _during, _goodput,
             lambda v: v is not None and v >= lab.GOODPUT_MIN, key="goodput"),
    GoalSpec("", "during", "", _during, _fast,
             lambda v: v is not None and v < lab.FAST_MAX, key="fast"),
    GoalSpec("", "after", "", _after, _recovered,
             lambda v: v is not None and v <= lab.RECOVERY, key="recovered"),
]


class OverloadWorld(World):
    id = "overload"
    view = "lanes"
    stage_colours = (RED, EXTRA2, EXTRA1, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first_try"), ([EXTRA1, EXTRA2], "retries"),
              (WASTED, "wasted"), (RED, "rejected"), (GREEN, "in_time"),
              (LIMIT, "max", "┄"), (INCIDENT_KEY, "incident", "█")]
    incident_verbs = ("spike", "calm")

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "capacity":
            return self.word("drop" if start else "up")
        return self.word("spike" if start else "calm")

    tables = {
        "requests": Table(sort=REQ_FIRST, times=(REQ_FIRST, REQ_DONE)),
        "tries": Table(sort=TRY_SENT, times=(TRY_SENT, TRY_END)),
        "work": Table(sort=WORK_START, times=(WORK_START, WORK_END)),
        "queue": Table(sort=Q_T, times=(Q_T,)),
    }
    goals = GOALS
    chart_top = 300.0

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 75.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["tries"]:
            run.add(f"try{min(r[TRY_ATTEMPT], 2)}", r[TRY_SENT])
            if r[TRY_ATTEMPT] == 0:
                run.add("first", r[TRY_SENT])
            name = {OK: "ok", GAVE_UP: "gave_up", REJECTED: "rejected"}[r[TRY_RESULT]]
            run.add(name, r[TRY_END])
        for w in tables["work"]:
            run.add({IN_TIME: "in_time", LATE: "late"}.get(w[WORK_KIND], "skipped"), w[WORK_START])
        for q in tables["requests"]:
            name = {SERVED: "served", FAILED: "failed", REFUSED: "refused"}[q[REQ_OUTCOME]]
            run.add(name, q[REQ_DONE])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        a, b = _busy(inc)
        for q in run.rows("queue", a, b):
            if q[Q_LEN] > lab.QUEUE_MAX:
                return [(q[Q_T], self.s("warn_queue", limit=lab.QUEUE_MAX))]
        for s in _seconds(a, b):
            late, done = run.series("late", s, s + 1)[0], run.series("in_time", s, s + 1)[0]
            if late and late / (late + done) > 0.5:
                return [(s + 1.0, self.s("warn_waste", share=late / (late + done)))]
        return []

    def incident_title(self, inc: Incident) -> str:
        name = self.s("capacity_drop") if inc.kind == "capacity" else self.s("spike")
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s("back_to_normal")
        if inc.kind == "capacity":
            return self.s("capacity_down", share=inc.severity, cause=self.cause(inc))
        return self.s("traffic_up", factor=inc.severity, cause=self.cause(inc))

    def queue_at(self, run: Run, t: float) -> tuple[int, int]:
        """(waiting, of those already given up) at t, from the last sample."""
        keys = run.keys.get("queue", [])
        i = bisect_right(keys, t) - 1
        if i < 0:
            return 0, 0
        q = run.tables["queue"][i]
        return q[Q_LEN], q[Q_STALE]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        def goodput_s(s: int) -> tuple[float, str]:
            ok, asked = run.series("ok", s, s + 1)[0], run.series("first", s, s + 1)[0]
            possible = min(capacity_at(run, s + 0.5), asked)
            v = ok / possible if possible else 1.0
            return v, "bad" if v < lab.GOODPUT_MIN else "warn" if v < 0.95 else "ok"

        def waste_s(s: int) -> tuple[float, str]:
            late, done = run.series("late", s, s + 1)[0], run.series("in_time", s, s + 1)[0]
            v = late / (late + done) if late + done else 0.0
            return v, "bad" if v >= lab.WASTE_MAX else "ok"

        def fast_s(s: int) -> tuple[float, str]:
            v = percentile([r[TRY_END] - r[TRY_SENT] for r in _in_time(run, s, s + 1, s + 1)], 50)
            if v is None:
                return 0.0, "idle"
            return v, "bad" if v >= lab.FAST_MAX else "warn" if v >= 0.15 else "ok"

        last = int(t) - 1
        gv, gs = goodput_s(last) if last >= 0 else (1.0, "idle")
        wv, ws = waste_s(last) if last >= 0 else (0.0, "idle")
        fv = percentile([r[TRY_END] - r[TRY_SENT] for r in _in_time(run, t - 5, t, t)], 50)
        fs = "idle" if fv is None else "bad" if fv >= lab.FAST_MAX else "warn" if fv >= 0.15 else "ok"
        tiles = [
            Tile(self.s("tile_served"), f"{gv:.0%}", "≥80%", gs, history(run, t, goodput_s)),
            Tile(self.s("tile_waste"), f"{wv:.0%}", "<5%", ws, history(run, t, waste_s)),
            Tile(self.s("tile_reply"), fmt_ms(fv), "<300ms", fs, history(run, t, fast_s)),
        ]
        tries = run.rows("tries", t - 1, t)
        rounds = [0, 0, 0]
        for r in tries:
            rounds[min(r[TRY_ATTEMPT], 2)] += 1
        work = run.rows("work", t - 1, t)
        in_time = sum(w[WORK_KIND] == IN_TIME for w in work)
        wasted = sum(w[WORK_KIND] == LATE for w in work)
        rejected = sum(1 for r in run.rows("tries", t - 1, t) if r[TRY_RESULT] == REJECTED)
        bars = [
            Bar(self.s("bar_arrive"), [(float(n), TRIES[k]) for k, n in enumerate(rounds)]),
            Bar(self.s("bar_server"), [(float(in_time), GREEN), (float(wasted), WASTED)]),
            Bar(self.s("bar_rejected"), [(float(rejected), RED)]),
        ]
        headline, colour = self._headline(run, t, in_time, wasted, rejected)
        return Traffic(tiles, bars, lab.CAPACITY, self.s("max", limit=lab.CAPACITY), headline, colour,
                       title=self.s("toplist"), top=400.0)

    def _headline(self, run: Run, t: float, in_time: int, wasted: int, rejected: int):
        done = in_time + wasted
        if done and wasted / done > 0.5:
            return self.s("head_wasted", share=wasted / done), RED
        waiting, _ = self.queue_at(run, t)
        if capacity_at(run, t) < lab.CAPACITY:
            return self.s("head_capacity", capacity=capacity_at(run, t), waiting=waiting), EXTRA2
        if rejected:
            return self.s("head_rejecting"), BLUE
        return self.s("head_ok"), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("requests", 0.0)
        partial = [r for r in run.rows("requests", s - span - 1, t) if s <= r[REQ_DONE] < t]

        def total(name: str, outcome: int) -> float:
            return run.total(name, t) + sum(1 for r in partial if r[REQ_OUTCOME] == outcome)

        served, failed, refused = total("served", SERVED), total("failed", FAILED), total("refused", REFUSED)
        waiting = len(run.active("requests", t, REQ_DONE))
        recent = [r[REQ_DONE] - r[REQ_FIRST] for r in run.rows("requests", t - 5 - span, t)
                  if t - 5 <= r[REQ_DONE] < t and r[REQ_OUTCOME] == SERVED]
        words = self.screen.STATS
        return [
            (words["served"], fmt_int(served), GREEN),
            (self.s("stat_gave_up"), fmt_int(failed), EXTRA2 if failed else MUTED),
            (self.s("stat_rejected"), fmt_int(refused), RED if refused else MUTED),
            (words["waiting"], fmt_int(waiting), EXTRA2 if waiting > 50 else WHITE),
            (words["p50"], fmt_ms(percentile(recent, 50)), WHITE),
            (words["p99"], fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(TRIES[k], run.hist.get(f"try{k}", [])) for k in range(3)]

    def chart_limit(self):
        return lab.CAPACITY, f"{lab.CAPACITY:.0f}/s"

    def legend_notes(self) -> list[str]:
        return [self.s("note_dots")]


WORLD = OverloadWorld
