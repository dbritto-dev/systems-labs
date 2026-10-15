"""World for lab hedged_requests. Its words are in labs/hedged_requests/text/<lang>.py."""

from __future__ import annotations

from labs.hedged_requests import lab
from labs.hedged_requests.scenario import DEADLINE, OK, REPLICAS
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, RGB, WHITE,
)
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

DOWN_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
SLOW = 0.020  # a read without an answer after this long is slow (the reference hedges here)

REQ_ID, REQ_START, REQ_END, REQ_OUTCOME, REQ_COPIES, REQ_HEDGED = range(6)
CALL_START, CALL_REQ, CALL_REPLICA, CALL_END, CALL_OUTCOME, CALL_COPY, CALL_WASTED = range(7)


def _slow_replicas(inc: Incident | None) -> set[int]:
    """The replicas an incident slows down."""
    if inc is None:
        return set()
    return set(range(REPLICAS)) if inc.kind == "all" else {int(inc.kind[1:])}


def _p99(rows: list[tuple]) -> float | None:
    return percentile([r[REQ_END] - r[REQ_START] for r in rows], 99)


def _extra(rows: list[tuple]) -> float | None:
    """Calls beyond the first, per read."""
    return sum(r[REQ_COPIES] for r in rows) / len(rows) - 1.0 if rows else None


def _waste(calls: list[tuple]) -> float | None:
    """The share of the replicas' time spent on calls whose read was already answered."""
    busy = sum(c[CALL_END] - c[CALL_START] for c in calls)
    return sum(c[CALL_WASTED] for c in calls) / busy if busy > 0 else None


def _ended(run: Run, table: str, a: float, b: float, upto: float, end: int) -> list[tuple]:
    """Rows started in [a, b) that had ended by `upto`."""
    return [r for r in run.rows(table, a, min(b, upto)) if r[end] <= upto]


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0 - 2.0


def _tail(run: Run, inc: Incident, upto: float):
    """The p99 of a read before the incident: the rare slow replies set it, unless you hedge."""
    v = _p99(_ended(run, "requests", *_before(inc), upto, REQ_END))
    return (None, "–") if v is None else (v, fmt_ms(v))


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _extra_load(run: Run, inc: Incident, upto: float):
    v = _extra(_ended(run, "requests", inc.t0, inc.t1, upto, REQ_END))
    return (None, "–") if v is None else (v, f"+{v:.0%}")


def _wasted(run: Run, inc: Incident, upto: float):
    v = _waste(_ended(run, "calls", inc.t0, inc.t1, upto, CALL_END))
    return (None, "–") if v is None else (v, f"{v:.0%}")


def _served(run: Run, inc: Incident, upto: float):
    rows = _ended(run, "requests", inc.t0, inc.t1, upto, REQ_END)
    if not rows:
        return None, "–"
    v = sum(r[REQ_OUTCOME] == OK for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.AFTER[0], inc.t1 + lab.AFTER[1]


def _back(run: Run, inc: Incident, upto: float):
    v = _p99(_ended(run, "requests", *_after(inc), upto, REQ_END))
    return (None, "–") if v is None else (v, fmt_ms(v))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _tail,
             lambda v: v is not None and v <= lab.TAIL_MAX, settle_extra=DEADLINE, key="tail"),
    GoalSpec("", "during", "", _during, _extra_load,
             lambda v: v is not None and v <= lab.EXTRA_MAX, settle_extra=DEADLINE, key="extra"),
    GoalSpec("", "during", "", _during, _wasted,
             lambda v: v is not None and v <= lab.WASTE_MAX, settle_extra=DEADLINE + 0.5, key="waste"),
    GoalSpec("", "during", "", _during, _served,
             lambda v: v is not None and v >= lab.SERVED_MIN, settle_extra=DEADLINE, key="served"),
    GoalSpec("", "after", "", _after, _back,
             lambda v: v is not None and v <= lab.TAIL_MAX, settle_extra=DEADLINE, key="back"),
]


class HedgedRequestsWorld(World):
    id = "hedged_requests"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first_call"), (EXTRA1, "slow_reply"), (EXTRA2, "copy"),
              (EXTRA3, "wasted"), (RED, "failed"), (GREEN, "served"), (LIMIT, "limit", "┄"),
              (DOWN_KEY, "incident", "█")]
    incident_verbs = ("slow", "fast")
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "calls": Table(sort=CALL_START, times=(CALL_START, CALL_END)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 100.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("served" if r[REQ_OUTCOME] == OK else "failed", r[REQ_END])
            run.add("asked", r[REQ_START])
            run.add("copies", r[REQ_START], r[REQ_COPIES] - 1)
        for c in tables["calls"]:
            run.add("busy", c[CALL_START], c[CALL_END] - c[CALL_START])
            run.add("wasted", c[CALL_START], c[CALL_WASTED])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1)):
            asked, copies = run.series("asked", s, s + 1)[0], run.series("copies", s, s + 1)[0]
            if asked and copies / asked > 2 * lab.EXTRA_MAX:
                return [(s + 1.0 + DEADLINE, self.s("warn_extra", extra=copies / asked))]
        return []

    def replica_name(self, i: int) -> str:
        return self.s("replica", n=i + 1)

    def incident_title(self, inc: Incident) -> str:
        if inc.kind == "all":
            name = self.s("title_all")
        else:
            name = self.s("title_one", replica=self.replica_name(int(inc.kind[1:])))
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if inc.kind == "all":
            if start:
                return self.s("slow_all", ms=fmt_ms(inc.severity), cause=self.cause(inc))
            return self.s("fast_all")
        name = self.replica_name(int(inc.kind[1:]))
        if start:
            return self.s("slow_one", replica=name, ms=fmt_ms(inc.severity), cause=self.cause(inc))
        return self.s("fast_one", replica=name)

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def ended(self, run: Run, t: float, seconds: float) -> list[tuple]:
        """Reads that ended in the last `seconds` before t."""
        span = run.max_dur.get("requests", 0.0)
        return [r for r in run.rows("requests", t - seconds - span, t) if t - seconds <= r[REQ_END] < t]

    def calls_ended(self, run: Run, t: float, seconds: float) -> list[tuple]:
        span = run.max_dur.get("calls", 0.0)
        return [c for c in run.rows("calls", t - seconds - span, t) if t - seconds <= c[CALL_END] < t]

    def load_at(self, run: Run, t: float) -> tuple[float, float | None]:
        """(calls started in the last second / reads started in it, the extra share) at t."""
        reads = run.count("requests", t - 1, t)
        calls = run.count("calls", t - 1, t)
        return (calls / reads if reads else 1.0), (calls / reads - 1.0 if reads >= 10 else None)

    def door_at(self, run: Run, t: float) -> float | None:
        """While the client hedges at all: the share of slow reads in the last 2 s that got no copy
        (the budget said no). None when nothing hedged in the last 10 s (no hedging to refuse)."""
        if not any(r[REQ_COPIES] > 1 for r in run.rows("requests", t - 10, t) if r[REQ_END] < t):
            return None
        slow = [r for r in self.ended(run, t, 2.0) if r[REQ_END] - r[REQ_START] > SLOW + 0.003]
        if len(slow) < 3:
            return 0.0
        return sum(r[REQ_COPIES] == 1 for r in slow) / len(slow)

    # ---------------------------------------------------------------- panel

    def _per_second(self, run: Run, t: float):
        """The last 30 s by second: (p99, extra, waste) of reads and calls that ended in it."""
        end = int(t)
        reads: dict[int, list[tuple]] = {}
        for r in self.ended(run, end, 30.0):
            reads.setdefault(int(r[REQ_END]), []).append(r)
        calls: dict[int, list[tuple]] = {}
        for c in self.calls_ended(run, end, 30.0):
            calls.setdefault(int(c[CALL_END]), []).append(c)
        return reads, calls

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        recent = self.ended(run, t, 5.0)
        p99, extra = _p99(recent), _extra(recent)
        waste = _waste(self.calls_ended(run, t, 5.0))
        reads, calls = self._per_second(run, t)

        def tail_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.TAIL_MAX else "warn" if v > 0.8 * lab.TAIL_MAX else "ok"

        def extra_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.EXTRA_MAX else "warn" if v > 0.7 * lab.EXTRA_MAX else "ok"

        def waste_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.WASTE_MAX else "warn" if v > 0.5 * lab.WASTE_MAX else "ok"

        def tail_s(s: int):
            v = _p99(reads.get(s, []))
            return (v or 0.0), tail_state(v)

        def extra_s(s: int):
            v = _extra(reads.get(s, []))
            return (v or 0.0), extra_state(v)

        def waste_s(s: int):
            v = _waste(calls.get(s, []))
            return (v or 0.0), waste_state(v)

        tiles = [
            Tile("p99", fmt_ms(p99), f"≤{lab.TAIL_MAX * 1000:.0f}ms", tail_state(p99), history(run, t, tail_s)),
            Tile(self.s("tile_extra"), "–" if extra is None else f"+{extra:.0%}", f"≤{lab.EXTRA_MAX:.0%}",
                 extra_state(extra), history(run, t, extra_s)),
            Tile(self.s("tile_waste"), "–" if waste is None else f"{waste:.0%}", f"≤{lab.WASTE_MAX:.0%}",
                 waste_state(waste), history(run, t, waste_s)),
        ]
        last = run.rows("calls", t - 1, t)
        bars = []
        for i in range(REPLICAS):
            first = sum(c[CALL_REPLICA] == i and c[CALL_COPY] == 0 for c in last)
            copies = sum(c[CALL_REPLICA] == i and c[CALL_COPY] > 0 for c in last)
            bars.append(Bar(self.replica_name(i), [(first, WHITE), (copies, EXTRA2)]))
        headline, colour = self._headline(variant, t, p99, extra)
        return Traffic(tiles, bars, 0.0, "", headline, colour)

    def _headline(self, variant: str, t: float, p99: float | None, extra: float | None):
        inc = self.incident_at(variant, t)
        hedging = extra is not None and extra > 0.005
        if inc is not None and inc.kind == "all":
            if extra is not None and extra > lab.EXTRA_MAX:
                return self.s("head_all_storm", extra=extra), RED
            return self.s("head_all_capped"), BLUE if hedging else EXTRA2
        if inc is not None:
            name = self.replica_name(int(inc.kind[1:]))
            if extra is not None and extra > lab.EXTRA_MAX:
                return self.s("head_one_hidden", replica=name, extra=extra), EXTRA2
            if hedging:
                return self.s("head_one_capped", replica=name), BLUE
            return self.s("head_one_waits", replica=name), EXTRA2
        last = self.current_incident(variant, t)
        if last is not None and last.t1 <= t < last.t1 + 5 + DEADLINE:
            return self.s("head_back"), BLUE  # the last slow reads of the incident still count
        if p99 is not None and p99 > lab.TAIL_MAX:
            return self.s("head_tail", p99=fmt_ms(p99)), EXTRA2
        if hedging:
            return self.s("head_hedged", p99=fmt_ms(p99)), BLUE
        return self.s("head_calm"), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("requests", 0.0)
        partial = [r for r in run.rows("requests", s - span - 1, t) if s <= r[REQ_END] < t]
        served = run.total("served", t) + sum(r[REQ_OUTCOME] == OK for r in partial)
        failed = run.total("failed", t) + sum(r[REQ_OUTCOME] != OK for r in partial)
        waiting = len(run.active("requests", t, REQ_END))
        recent = [r[REQ_END] - r[REQ_START] for r in self.ended(run, t, 5.0)]
        words = self.screen.STATS
        return [
            (words["served"], fmt_int(served), GREEN),
            (words["failed"], fmt_int(failed), RED if failed else MUTED),
            (words["waiting"], fmt_int(waiting), EXTRA2 if waiting > 20 else WHITE),
            (words["p99"], fmt_ms(percentile(recent, 99)), WHITE),
            ("p999", fmt_ms(percentile(recent, 99.9)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA2, run.hist.get("copies", []))]

    def chart_limit(self):
        return self.rate * lab.EXTRA_MAX, self.s("chart_limit", extra=lab.EXTRA_MAX)

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = HedgedRequestsWorld
