"""World for lab deadlock_avoidance. Its words are in labs/deadlock_avoidance/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.deadlock_avoidance import lab
from labs.deadlock_avoidance.scenario import BATCH, WORKERS
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, MUTED, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, history, percentile,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

T_ID, T_START, T_END, T_OK, T_DONE, T_KIND, T_SRC, T_DST, T_OUTCOME, T_TRIES, T_WAIT = range(11)
W_T0, W_T1, W_ID, W_HELD, W_WANT, W_RESULT = range(6)
C_T0, C_T1, C_ACCOUNTS = range(3)
S_T, S_BUSY, S_DOOR, S_WAITING, S_DRIFT, S_CYCLES = range(6)

_s = strings("deadlock_avoidance")  # one of the lab's STRINGS, for the goal measures below


def tries_colour(tries: int):
    """White a first try; light, mid, deep orange after one, two, three or more retries."""
    return WHITE if tries <= 1 else EXTRA1 if tries == 2 else EXTRA2 if tries == 3 else EXTRA3


# ---------------------------------------------------------------- goals


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _checked(inc: Incident) -> tuple[float, float]:
    """The incident, and a few seconds after it: what it did to the balances."""
    return inc.t0, inc.t1 + lab.CHECK


def _ended(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Transfers that started in [a, b) and whose client had its answer by `upto`."""
    return [r for r in run.rows("transfers", a, min(b, upto)) if r[T_END] <= upto]


def _frozen(run: Run, inc: Incident, upto: float) -> list[tuple]:
    """Deadlocks that began during the incident and lasted FROZEN seconds (by `upto`)."""
    a, b = _during(inc)
    return [c for c in run.rows("cycles", a, min(b, upto)) if min(c[C_T1], upto) - c[C_T0] >= lab.FROZEN]


def _deadlocks(run: Run, inc: Incident, upto: float):
    if upto <= inc.t0:
        return NO_VALUE
    n = len(_frozen(run, inc, upto))
    return n, _s("count", n=n)


def _doomed_deadlocks(run: Run, inc: Incident, upto: float) -> bool:
    return bool(_frozen(run, inc, upto))


def _completed(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_during(inc), upto)
    if not done:
        return NO_VALUE
    v = sum(1 for r in done if r[T_OK]) / len(done)
    return v, f"{v:.1%}"


def _p99(run: Run, inc: Incident, upto: float):
    v = percentile([r[T_END] - r[T_START] for r in _ended(run, *_during(inc), upto) if r[T_KIND] != BATCH], 99)
    if v is None:
        return NO_VALUE
    return v, f"{v * 1000:.0f}ms"


def _retries(run: Run, inc: Incident, upto: float):
    done = _ended(run, *_during(inc), upto)
    if not done:
        return NO_VALUE
    v = sum(max(0, r[T_TRIES] - 1) for r in done) / len(done)
    return v, f"{v:.2f}"


def _drift(run: Run, inc: Incident, upto: float):
    """Money created or destroyed between the start of the incident and `upto` (cents)."""
    a, b = _checked(inc)
    rows = run.rows("samples", a - 1.0, min(b, upto) + 1e-9)
    if not rows or upto <= a:
        return None
    before = [x for x in rows if x[S_T] <= a]
    base = before[-1][S_DRIFT] if before else rows[0][S_DRIFT]
    return rows[-1][S_DRIFT] - base


def _money(run: Run, inc: Incident, upto: float):
    v = _drift(run, inc, upto)
    if v is None:
        return NO_VALUE
    return v, _s("money", amount=f"{v / 100:,.2f}")


def _doomed_money(run: Run, inc: Incident, upto: float) -> bool:
    return bool(_drift(run, inc, upto))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _during, _deadlocks, lambda v: v == 0,
             doomed=_doomed_deadlocks, settle_extra=lab.SETTLE, key="deadlocks"),
    GoalSpec("", "during", "", _during, _completed,
             at_least(lab.COMPLETED_MIN), settle_extra=lab.SETTLE, key="completed"),
    GoalSpec("", "during", "", _during, _p99, at_most(lab.P99_MAX), settle_extra=lab.SETTLE, key="p99"),
    GoalSpec("", "during", "", _during, _retries, at_most(lab.RETRIES_MAX), settle_extra=lab.SETTLE, key="retries"),
    GoalSpec("", "after", "", _checked, _money, lambda v: v == 0,
             doomed=_doomed_money, settle_extra=1.0, key="money"),
]


class DeadlockAvoidanceWorld(World):
    id = "deadlock_avoidance"
    view = "lanes"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first_try"), ([EXTRA1, EXTRA2, EXTRA3], "retries"),
              (GREEN, "done"), (RED, "deadlock"), (BLUE, "account"), (DOWN_KEY, "incident", "█")]
    tables = {
        "transfers": Table(sort=T_START, times=(T_START, T_END)),
        "waits": Table(sort=W_T0, times=(W_T0, W_T1)),
        "cycles": Table(sort=C_T0, times=(C_T0, C_T1)),
        "samples": Table(sort=S_T, times=(S_T,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 200.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["transfers"]:
            run.add("asks", r[T_START])
            if r[T_OK]:
                run.add("served", r[T_END])
                run.add("first" if r[T_TRIES] <= 1 else "retried", r[T_END])
            else:
                run.add("failed", r[T_END])
            if r[T_TRIES] > 1:
                run.add("retries", r[T_END], r[T_TRIES] - 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", rate=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        out = []
        cycles = run.rows("cycles", inc.t0, inc.t1)
        frozen = [c for c in cycles if c[C_T1] - c[C_T0] >= lab.FROZEN]
        if frozen:
            longest = max(c[C_T1] - c[C_T0] for c in frozen)
            out.append((inc.t1, self.s("warn_frozen", n=len(frozen), seconds=longest)))
        elif cycles:
            out.append((inc.t1, self.s("warn_broken", n=len(cycles))))
        done = [r for r in run.rows("transfers", inc.t0, inc.t1)]
        retries = sum(max(0, r[T_TRIES] - 1) for r in done)
        if retries:
            out.append((inc.t1, self.s("warn_retries", n=retries)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < max(i.t1, i.t0 + 1.0)), None)

    @staticmethod
    def sample_at(run: Run, t: float) -> tuple | None:
        """The latest look at the locks and the workers at or before t."""
        rows = run.rows("samples", t - 0.5, t + 1e-9)
        return rows[-1] if rows else None

    def cycles_at(self, run: Run, t: float) -> list[tuple]:
        """Deadlocks alive at t."""
        return run.active("cycles", t, C_T1)

    # ---------------------------------------------------------------- panel

    def _recent(self, run: Run, t: float, span: float) -> list[tuple]:
        longest = run.max_dur.get("transfers", 0.0)
        return [r for r in run.rows("transfers", t - span - longest, t) if t - span <= r[T_END] < t]

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        recent = self._recent(run, t, 10.0)
        users = [r[T_END] - r[T_START] for r in recent if r[T_KIND] != BATCH]
        p99 = percentile(users, 99)
        retries = sum(max(0, r[T_TRIES] - 1) for r in recent) / len(recent) if recent else None
        sample = self.sample_at(run, t)
        alive = sample[S_CYCLES] if sample else 0

        def deadlocks_s(s: int):
            rows = run.rows("samples", s, s + 1)
            v = max((x[S_CYCLES] for x in rows), default=0)
            return v, "bad" if v else "ok"

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.P99_MAX else "warn" if v > 0.6 * lab.P99_MAX else "ok"

        def p99_s(s: int):
            span = run.max_dur.get("transfers", 0.0)
            v = percentile([r[T_END] - r[T_START] for r in run.rows("transfers", s - span, s + 1)
                            if s <= r[T_END] < s + 1 and r[T_KIND] != BATCH], 99)
            return (v or 0.0), p99_state(v)

        def retry_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.RETRIES_MAX else "warn" if v > 0.02 else "ok"

        def retries_s(s: int):
            asks = run.series("asks", s, s + 1)[0]
            v = run.series("retries", s, s + 1)[0] / asks if asks else None
            return (v or 0.0), retry_state(v)

        tiles = [
            Tile(self.s("tile_deadlocks"), f"{alive}", "=0", "bad" if alive else "ok", history(run, t, deadlocks_s)),
            Tile(self.s("tile_p99"), "–" if p99 is None else f"{p99 * 1000:.0f}ms", f"≤{lab.P99_MAX * 1000:.0f}ms",
                 p99_state(p99), history(run, t, p99_s)),
            Tile(self.s("tile_retries"), "–" if retries is None else f"{retries:.2f}", f"≤{lab.RETRIES_MAX}",
                 retry_state(retries), history(run, t, retries_s)),
        ]
        last = self._recent(run, t, 1.0)
        first = sum(1 for r in last if r[T_OK] and r[T_TRIES] <= 1)
        retried = sum(1 for r in last if r[T_OK] and r[T_TRIES] > 1)
        failed = len(last) - first - retried
        tries = sum(max(0, r[T_TRIES] - 1) for r in last)
        asked = run.count("transfers", t - 1, t)
        bars = [
            Bar(self.s("bar_asked"), [(float(asked), WHITE)]),
            Bar(self.s("bar_done"), [(float(first), WHITE), (float(retried), EXTRA2), (float(failed), RED)]),
            Bar(self.s("bar_retries"), [(float(tries), EXTRA1)]),
        ]
        inc = self.incident_at(variant, t)
        if alive:
            headline, colour = self.s("head_deadlock", n=alive), RED
        elif sample is not None and sample[S_BUSY] >= WORKERS:
            headline, colour = self.s("head_frozen"), RED
        elif tries:
            headline, colour = self.s("head_retries", n=tries), EXTRA2
        elif inc is not None:
            headline, colour = self.s(f"head_{inc.kind}"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("title"))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "transfers", T_START, T_END, T_OK, t, busy=WORKERS // 2)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("first", [])), (EXTRA2, run.hist.get("retried", [])),
                (RED, run.hist.get("failed", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = DeadlockAvoidanceWorld
