"""World for lab idempotency. Its words are in labs/idempotency/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.idempotency import lab
from live.canvas import (
    BLUE, EXTRA, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE,
)
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, baseline_window, below, history,
    percentile,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
INF = float("inf")

PAY_ID, PAY_START, PAY_END, PAY_OK, PAY_TRIES, PAY_CHARGES, PAY_ANSWERS = range(7)
TRY_START, TRY_PAY, TRY_N, TRY_END, TRY_OUTCOME, TRY_CHARGED, TRY_AFTER, TRY_DUP = range(8)

_s = strings("idempotency")  # one of the lab's STRINGS, for the goal measures below


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _replay_window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER


def _ended(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Payments that started in [a, b) and finished by `upto`."""
    return [p for p in run.rows("payments", a, min(b, upto)) if p[PAY_END] <= upto]


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    b = min(b, upto)
    done = [p for p in run.rows("payments", a - run.max_dur.get("payments", 0.0), b) if a <= p[PAY_END] < b]
    if not done:
        return NO_VALUE
    v = sum(p[PAY_OK] for p in done) / len(done)
    return v, f"{v:.0%}"


def _replay(run: Run, inc: Incident, upto: float):
    a, b = _replay_window(inc)
    late = [r for r in run.rows("attempts", a, min(b, upto)) if r[TRY_AFTER] and r[TRY_END] <= upto]
    if not late:
        return None, _s("none")  # no retry came after a finished charge: nothing to replay
    v = sum(1 for r in late if not r[TRY_CHARGED]) / len(late)
    return v, f"{v:.0%}"


def _doubles(run: Run, inc: Incident, upto: float):
    paid = _ended(run, *_during(inc), upto)
    if not paid:
        return NO_VALUE
    n = sum(1 for p in paid if p[PAY_CHARGES] > 1)
    return n, _s("doubles", n=n)


def _doomed_doubles(run: Run, inc: Incident, upto: float) -> bool:
    return any(p[PAY_CHARGES] > 1 for p in _ended(run, *_during(inc), upto))


def _different(run: Run, inc: Incident, upto: float):
    paid = _ended(run, *_during(inc), upto)
    if not paid:
        return NO_VALUE
    n = sum(1 for p in paid if p[PAY_ANSWERS] > 1)
    return n, _s("doubles", n=n)


def _doomed_different(run: Run, inc: Incident, upto: float) -> bool:
    return any(p[PAY_ANSWERS] > 1 for p in _ended(run, *_during(inc), upto))


def _fast(run: Run, inc: Incident, upto: float):
    times = [(p[PAY_END] - p[PAY_START]) if p[PAY_OK] else INF for p in _ended(run, *_after(inc), upto)]
    v = percentile(times, 99)
    if v is None:
        return NO_VALUE
    return v, "∞" if v == INF else f"{v * 1000:.0f}ms"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), key="baseline"),
    GoalSpec("", "during", "", _replay_window, _replay,
             lambda v: v is None or v >= lab.REPLAY_MIN, settle_extra=lab.SETTLE, key="replay"),
    GoalSpec("", "during", "", _during, _doubles, lambda v: v == 0,
             doomed=_doomed_doubles, settle_extra=lab.SETTLE, key="once"),
    GoalSpec("", "during", "", _during, _different, lambda v: v == 0,
             doomed=_doomed_different, settle_extra=lab.SETTLE, key="same"),
    GoalSpec("", "after", "", _after, _fast, below(lab.P99_MAX), settle_extra=lab.SETTLE, key="fast"),
]


class IdempotencyWorld(World):
    id = "idempotency"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first_try"), ([EXTRA1, EXTRA2, EXTRA3], "retries"),
              (RED, "double"), (GREEN, "answered"), (MUTED, "lost"), (LIMIT, "limit", "┄"),
              (DOWN_KEY, "incident", "█")]
    incident_verbs = ("slow", "calm")
    tables = {
        "payments": Table(sort=PAY_START, times=(PAY_START, PAY_END)),
        "attempts": Table(sort=TRY_START, times=(TRY_START, TRY_END)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 40.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for p in tables["payments"]:
            run.add("pays", p[PAY_START])
            run.add("served" if p[PAY_OK] else "failed", p[PAY_END])
            if p[PAY_TRIES] > 1:
                run.add("retried", p[PAY_START])
            if p[PAY_CHARGES] > 1:
                run.add("double_pays", p[PAY_END])
        for r in tables["attempts"]:
            run.add(f"r{min(r[TRY_N], 3)}", r[TRY_START])
            if r[TRY_CHARGED]:
                run.add("dup_charges" if r[TRY_DUP] else "first_charges", r[TRY_END])
            if r[TRY_AFTER]:
                run.add("late", r[TRY_START])
                if not r[TRY_CHARGED]:
                    run.add("replayed", r[TRY_START])

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", seconds=inc.severity, share=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        n = sum(1 for p in run.rows("payments", inc.t0, inc.t1) if p[PAY_CHARGES] > 1)
        return [(inc.t1, self.s("warn_double", n=n))] if n else []

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = run.max_dur.get("payments", 0.0)
        recent = [p for p in run.rows("payments", t - 10 - span, t) if t - 10 <= p[PAY_END] < t]
        doubles = sum(1 for p in recent if p[PAY_CHARGES] > 1)

        def doubles_s(s: int):
            v = run.series("double_pays", s, s + 1)[0]
            return v, "bad" if v else "ok"

        late = [r for r in run.rows("attempts", t - 10, t) if r[TRY_AFTER]]
        replay = sum(1 for r in late if not r[TRY_CHARGED]) / len(late) if late else None

        def replay_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.REPLAY_MIN else "ok"

        def replay_s(s: int):
            n, ok = run.series("late", s, s + 1)[0], run.series("replayed", s, s + 1)[0]
            v = ok / n if n else None
            return (v or 0.0), replay_state(v)

        started = run.rows("payments", t - 10 - span, t - span) or run.rows("payments", t - 10, t)
        retried = sum(1 for p in started if p[PAY_TRIES] > 1) / len(started) if started else 0.0

        def retried_state(v: float) -> str:
            return "warn" if v > 0.1 else "ok"

        def retried_s(s: int):
            n, r = run.series("pays", s, s + 1)[0], run.series("retried", s, s + 1)[0]
            v = r / n if n else 0.0
            return v, retried_state(v)

        tiles = [
            Tile(self.s("tile_doubles"), str(doubles), "=0", "bad" if doubles else "ok", history(run, t, doubles_s)),
            Tile(self.s("tile_replayed"), "–" if replay is None else f"{replay:.0%}", "≥95%",
                 replay_state(replay), history(run, t, replay_s)),
            Tile(self.s("tile_retried"), f"{retried:.0%}", "", retried_state(retried), history(run, t, retried_s)),
        ]
        last = run.rows("attempts", t - 1, t)
        rounds = [0, 0, 0, 0]
        for r in last:
            rounds[min(r[TRY_N], 3)] += 1
        charged = [r for r in run.rows("attempts", t - 1 - run.max_dur.get("attempts", 0.0), t)
                   if r[TRY_CHARGED] and t - 1 <= r[TRY_END] < t]
        dups = sum(1 for r in charged if r[TRY_DUP])
        bars = [
            Bar(self.s("bar_tries"), [(float(n), EXTRA[k]) for k, n in enumerate(rounds)]),
            Bar(self.s("bar_charges"), [(float(len(charged) - dups), WHITE), (float(dups), RED)]),
        ]
        inc = self.incident_at(variant, t)
        if doubles:
            headline, colour = self.s("head_doubles", n=doubles), RED
        elif inc is not None and inc.kind == "slow":
            headline, colour = self.s("head_slow"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=self.rate * 3)

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "payments", PAY_START, PAY_END, PAY_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("first_charges", [])), (RED, run.hist.get("dup_charges", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    chart_top = 120.0

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = IdempotencyWorld
