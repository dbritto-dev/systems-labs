"""World for lab retry_storm."""

from __future__ import annotations

from labs.retry_storm import lab
from live.canvas import BLUE, EXTRA, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Stage, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_CALLS = range(5)
CALL_START, CALL_REQ, CALL_ATTEMPT, CALL_OK, CALL_END = range(5)


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


# ---------------------------------------------------------------- goals


def _baseline_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _baseline_window(inc)
    b = min(b, upto)
    ended = [r for r in run.rows("requests", a - run.max_dur.get("requests", 0), b)
             if a <= r[REQ_END] < b]
    if not ended:
        return None, "–"
    v = sum(r[REQ_OK] for r in ended) / len(ended)
    return v, f"{v:.0%}"


def _waits(run: Run, inc: Incident, upto: float) -> dict[int, list[float]]:
    """The wait before each retry during the incident, by retry round (1 = the first retry)."""
    b = min(inc.t1, upto)
    span = run.max_dur.get("requests", 0.0)
    ends = {(c[CALL_REQ], c[CALL_ATTEMPT]): c[CALL_END] for c in run.rows("calls", inc.t0 - span, b)}
    rounds: dict[int, list[float]] = {}
    for c in run.rows("calls", inc.t0, b):
        prev = ends.get((c[CALL_REQ], c[CALL_ATTEMPT] - 1))
        if c[CALL_ATTEMPT] > 0 and prev is not None:
            rounds.setdefault(c[CALL_ATTEMPT], []).append(c[CALL_START] - prev)
    return rounds


def _backoff(run: Run, inc: Incident, upto: float):
    """How much the average wait grows from one retry round to the next.

    Retrying straight away or 50 ms apart: about 1x (or no wait at all). Exponential backoff,
    with or without jitter, doubles it: about 2x.
    """
    rounds = _waits(run, inc, upto)
    growth = []
    for k in sorted(rounds):
        now, then = rounds[k], rounds.get(k + 1, [])
        if len(now) >= lab.BACKOFF_SAMPLES and len(then) >= lab.BACKOFF_SAMPLES:
            a, b = sum(now) / len(now), sum(then) / len(then)
            growth.append(b / a if a > 0.001 else 1.0)  # no wait at all: nothing grows
    if not growth:
        n = sum(len(w) for w in rounds.values())
        if n < lab.BACKOFF_SAMPLES:
            return None, "–"
        # Retries, but too few reach a second round to compare (a budget holding them back):
        # nothing piles up in waves, so it passes.
        return lab.BACKOFF_MIN, "few"
    v = sum(growth) / len(growth)
    return v, f"{v:.1f}x"


def _jitter(run: Run, inc: Incident, upto: float):
    """How much the wait before the same retry round varies between users (stdev / mean).

    Retries 50 ms apart, or plain exponential backoff, wait exactly the same in each round:
    every user comes back in lockstep (0%). Full jitter spreads them out (~58%).
    """
    rounds = _waits(run, inc, upto)
    n = sum(len(w) for w in rounds.values())
    if n < lab.JITTER_SAMPLES:
        return None, "–"
    spread = 0.0
    for waits in rounds.values():  # each round on its own, weighted by its size
        mean = sum(waits) / len(waits)
        if len(waits) > 1 and mean > 0:
            sd = (sum((w - mean) ** 2 for w in waits) / (len(waits) - 1)) ** 0.5
            spread += sd / mean * len(waits)
    v = spread / n
    return v, f"{v:.0%}"


def _base_rate(run: Run, inc: Incident) -> float:
    a, b = _baseline_window(inc)
    return run.count("calls", a, b) / (b - a)


def _retries(run: Run, inc: Incident, upto: float):
    rows = run.rows("calls", inc.t0, min(inc.t1, upto))
    if not rows:
        return None, "–"
    v = sum(1 for r in rows if r[CALL_ATTEMPT] > 0) / len(rows)
    return v, f"{v:.0%}"


def _load(run: Run, inc: Incident, upto: float):
    b = min(inc.t1, upto)
    if b <= inc.t0:
        return None, "–"
    base = _base_rate(run, inc)
    v = _ratio(run.count("calls", inc.t0, b) / (b - inc.t0), base)
    return v, "–" if v is None else f"avg {v:.1f}x"


def _load_doomed(run: Run, inc: Incident, upto: float) -> bool:
    # Even with no calls at all for the rest of the outage, the average stays too high.
    base = _base_rate(run, inc)
    so_far = run.count("calls", inc.t0, min(inc.t1, upto))
    return base > 0 and so_far >= lab.LOAD_MAX * base * (inc.t1 - inc.t0)


def _after_window(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER_WINDOW


def _served(run: Run, inc: Incident, upto: float):
    a, b = _after_window(inc)
    started = [r for r in run.rows("requests", a, min(b, upto)) if r[REQ_END] <= upto]
    if not started:
        return None, "–"
    v = sum(r[REQ_OK] for r in started) / len(started)
    return v, f"{v:.0%}"


GOALS = [
    GoalSpec("Baseline ok", "before", "Client must return results",
             _baseline_window, _baseline, lambda v: v is not None and v >= lab.BASELINE_MIN),
    GoalSpec("Retries ≥ 3%", "during", "retry ServiceError in Client",
             lambda i: (i.t0, i.t1), _retries, lambda v: v is not None and v >= lab.RETRIES_MIN),
    GoalSpec("Backoff ≥ 1.5x", "during", "sleep backoff_delay(attempt)",
             lambda i: (i.t0, i.t1), _backoff, lambda v: v is not None and v >= lab.BACKOFF_MIN),
    GoalSpec("Jitter ≥ 25%", "during", "add jitter to backoff_delay",
             lambda i: (i.t0, i.t1), _jitter, lambda v: v is not None and v >= lab.JITTER_MIN),
    GoalSpec("Load < 1.5x", "during", "spend a RetryBudget token",
             lambda i: (i.t0, i.t1), _load, lambda v: v is not None and v < lab.LOAD_MAX,
             doomed=_load_doomed),
    GoalSpec("Served ≥ 90%", "after", "retry once it is back",
             _after_window, _served, lambda v: v is not None and v >= lab.SERVED_MIN,
             settle_extra=6.0),
]


class RetryStormWorld(World):
    id = "retry_storm"
    title = "Retry storm"
    files = ("labs/retry_storm/main.py",)
    view = "lanes"
    stages = [Stage(label, story, colour, nxt) for (label, story, nxt), colour
              in zip(lab.STAGES, (RED, EXTRA3, EXTRA2, EXTRA1, BLUE))]
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first try"), ([EXTRA1, EXTRA2, EXTRA3], "retry 1,2,3"),
              (RED, "failed"), (GREEN, "served"), (LIMIT, "limit", "┄"), (DOWN_KEY, "incident", "█")]
    chart_top = lab.GAUGE_MAX
    incident_name = "Outage"
    incident_verbs = ("DOWN", "UP")
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
            run.add("ask", r[REQ_START])
            run.add("served" if r[REQ_OK] else "failed", r[REQ_END])
        for c in tables["calls"]:
            run.add(f"r{min(c[CALL_ATTEMPT], 3)}", c[CALL_START])
            run.add("calls", c[CALL_START])
            run.add("ok" if c[CALL_OK] else "err", c[CALL_END])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        base = _base_rate(run, inc)
        for s in range(int(inc.t0), int(inc.t1)):
            calls = run.series("calls", s, s + 1)[0]
            if base and calls / base >= lab.LOAD_MAX:
                return [(s + 1.0, f"load {calls / base:.1f}x what users ask")]
        return []

    def incident_title(self, inc: Incident) -> str:
        name = "Partial outage" if inc.kind == "errors" else "Outage"
        return f"{name} #{inc.index + 1}"

    def incident_text(self, inc: Incident, start: bool) -> str:
        if inc.kind == "errors":
            return f"is failing {inc.severity:.0%} of calls: {inc.cause}" if start else "is healthy again"
        return f"is down: {inc.cause}" if start else "is back up"

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def down_at(self, variant: str, t: float) -> bool:
        """In an incident (a full or a partial outage)."""
        return self.incident_at(variant, t) is not None

    def load_at(self, run: Run, t: float, window: float = 1.0) -> float:
        """Calls per second over the last `window` seconds."""
        return run.count("calls", t - window, t) / window

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        ask = run.count("requests", t - 2, t) / 2
        calls = self.load_at(run, t, 2.0)
        load = calls / ask if ask else 1.0
        down = self.down_at(variant, t)

        def load_state(v: float) -> str:
            return "bad" if v >= lab.LOAD_MAX else "warn" if v >= 1.2 else "ok"

        def load_s(s: int):
            a, c = run.series("ask", s, s + 1)[0], run.series("calls", s, s + 1)[0]
            v = c / a if a else 1.0
            return v, load_state(v)

        recent = run.rows("calls", t - 5, t)
        retries = sum(1 for r in recent if r[CALL_ATTEMPT] > 0) / len(recent) if recent else 0.0

        def retry_state(v: float, is_down: bool) -> str:
            return "bad" if is_down and v < lab.RETRIES_MIN else "ok"

        def retry_s(s: int):
            c = run.series("calls", s, s + 1)[0]
            r = c - run.series("r0", s, s + 1)[0]
            v = r / c if c else 0.0
            return v, retry_state(v, self.down_at(variant, s + 0.5))

        ended = [r for r in run.rows("requests", t - 5 - run.max_dur.get("requests", 0), t)
                 if t - 5 <= r[REQ_END] < t]
        served = sum(r[REQ_OK] for r in ended) / len(ended) if ended else 1.0

        def served_state(v: float) -> str:
            return "bad" if v < lab.SERVED_MIN else "warn" if v < 0.99 else "ok"

        def served_s(s: int):
            ok, bad = run.series("served", s, s + 1)[0], run.series("failed", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else 1.0
            return v, served_state(v)

        tiles = [
            Tile("Load", f"{load:.1f}x", "<1.5x", load_state(load), history(run, t, load_s)),
            Tile("Retries", f"{retries:.0%}", "≥3%", retry_state(retries, down),
                 history(run, t, retry_s)),
            Tile("Served", f"{served:.0%}", "≥90%", served_state(served), history(run, t, served_s)),
        ]
        last = run.rows("calls", t - 1, t)
        rounds = [0, 0, 0, 0]
        for r in last:
            rounds[min(r[CALL_ATTEMPT], 3)] += 1
        bars = [
            Bar("Users ask", [(run.count("requests", t - 1, t), WHITE)]),
            Bar("We get", [(float(n), EXTRA[k]) for k, n in enumerate(rounds)]),
        ]
        headline, colour = self._headline(variant, run, t, load)
        return Traffic(tiles, bars, lab.LIMIT, f"limit {lab.LIMIT:.0f}/s", headline, colour,
                       top=lab.GAUGE_MAX)

    def _headline(self, variant: str, run: Run, t: float, load: float):
        inc = self.current_incident(variant, t)
        if inc and inc.t0 <= t < inc.t1:
            colour = RED if load >= lab.LOAD_MAX else BLUE
            what = f"Failing {inc.severity:.0%}" if inc.kind == "errors" else "Down"
            return f"{what}: we get {load:.1f}x what users ask", colour
        if inc and inc.t1 <= t < inc.t1 + 10:
            for s in range(int(inc.t1), int(t)):
                a, c = run.series("ask", s, s + 1)[0], run.series("calls", s, s + 1)[0]
                f = run.series("failed", s, s + 1)[0]
                if a and c / a < 1.2 and f == 0:
                    return f"Recovered {max(0, s + 1 - inc.t1):.0f} s after the outage", BLUE
            return "Back up; retries still draining", MUTED
        return f"Load: {load:.1f}x what users ask", MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        partial = [r for r in run.rows("requests", s - run.max_dur.get("requests", 0) - 1, t)
                   if s <= r[REQ_END] < t]
        served = run.total("served", t) + sum(1 for r in partial if r[REQ_OK])
        failed = run.total("failed", t) + sum(1 for r in partial if not r[REQ_OK])
        waiting = len(run.active("requests", t, REQ_END))
        recent = [r[REQ_END] - r[REQ_START]
                  for r in run.rows("requests", t - 5 - run.max_dur.get("requests", 0), t)
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
        return [(EXTRA[k], run.hist.get(f"r{k}", [])) for k in range(4)]

    def chart_limit(self):
        return lab.LIMIT, f"{lab.LIMIT:.0f}/s"

    def legend_notes(self) -> list[str]:
        return ["Dots are a sample of calls, slowed down (cosmetic)."]


WORLD = RetryStormWorld
