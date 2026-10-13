"""World for lab conn_pool."""

from __future__ import annotations

from labs.conn_pool import lab
from labs.conn_pool.scenario import SAMPLE, TIMED_OUT, TOO_MANY
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Stage, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_WAIT, REQ_NEW, REQ_FAIL = range(7)
S_T, S_OPEN, S_BUSY = range(3)
INCIDENT_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
WAITED = 0.1  # a request that waited this long for a connection counts as "waited"


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Requests that ended in [a, b)."""
    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b]


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    rows = _ended(run, a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(r[REQ_OK] for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _reuse(run: Run, inc: Incident, upto: float):
    """Share of the requests that got a connection without opening a new one."""
    a, b = _before(inc)
    rows = [r for r in run.rows("requests", a, min(b, upto)) if r[REQ_OK]]
    if not rows:
        return None, "–"
    v = 1 - sum(r[REQ_NEW] for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _errors(run: Run, inc: Incident, upto: float):
    n = sum(r[REQ_FAIL] == TOO_MANY for r in _ended(run, inc.t0, min(inc.t1 + lab.SETTLE, upto)))
    return float(n), fmt_int(n)


def _errors_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return _errors(run, inc, upto)[0] > 0  # one refused connection is already too many


def _wait(run: Run, inc: Incident, upto: float):
    """p99 time waiting for a connection, for requests that started during the incident.

    A request still waiting when the incident is judged counts with the time it has waited so far.
    """
    cut = min(inc.t1 + lab.SETTLE, upto)
    rows = run.rows("requests", inc.t0, min(inc.t1, upto))
    waits = [min(r[REQ_WAIT], cut - r[REQ_START]) for r in rows]
    v = percentile(waits, 99)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER_WINDOW


def _recovered(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    cut = min(b + lab.SETTLE, upto)
    rows = run.rows("requests", a, min(b, upto))
    if not rows:
        return None, "–"
    good = sum(r[REQ_OK] and r[REQ_WAIT] < lab.WAIT_MAX and r[REQ_END] <= cut for r in rows)
    v = good / len(rows)
    return v, f"{v:.0%}"


GOALS = [
    GoalSpec("Baseline ok", "before", "the pool must hand out conns",
             _before, _baseline, lambda v: v is not None and v >= lab.BASELINE_MIN),
    GoalSpec("Reuse ≥ 90%", "before", "keep released connections",
             _before, _reuse, lambda v: v is not None and v >= lab.REUSE_MIN),
    GoalSpec("Conn errors = 0", "during", "cap the pool at max_size",
             _during, _errors, lambda v: v == 0, doomed=_errors_doomed, settle_extra=lab.SETTLE),
    GoalSpec("p99 wait < 1s", "during", "raise PoolTimeout sooner",
             _during, _wait, lambda v: v is not None and v < lab.WAIT_MAX, settle_extra=lab.SETTLE),
    GoalSpec("Recovered ≥ 95%", "after", "hand conns to waiters",
             _after, _recovered, lambda v: v is not None and v >= lab.RECOVERED_MIN,
             settle_extra=lab.SETTLE),
]


class ConnPoolWorld(World):
    id = "conn_pool"
    title = "Connection pool"
    files = ("labs/conn_pool/main.py",)
    view = "lanes"
    stages = [Stage(label, story, colour, nxt) for (label, story, nxt), colour
              in zip(lab.STAGES, (RED, EXTRA2, EXTRA1, BLUE))]
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "query"), (EXTRA1, "waits for a conn"),
              (EXTRA2, "opens a conn"), (RED, "failed"), (GREEN, "served"), (BLUE, "idle conn", "█"),
              (LIMIT, "limit", "┄"), (INCIDENT_KEY, "incident", "█")]
    incident_name = "Incident"
    incident_verbs = ("DOWN", "UP")

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "slowdown":
            return "SLOW" if start else "FAST"
        return "SPIKE" if start else "CALM"
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "samples": Table(sort=S_T, times=(S_T,)),
    }
    goals = GOALS
    chart_top = 60.0

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("ask", r[REQ_START])
            if r[REQ_NEW]:
                run.add("new", r[REQ_START])
            if r[REQ_OK]:
                run.add("served", r[REQ_END])
                run.add("opened" if r[REQ_NEW] else "waited" if r[REQ_WAIT] >= WAITED else "fast", r[REQ_END])
            else:
                run.add("failed", r[REQ_END])
                run.add("too_many" if r[REQ_FAIL] == TOO_MANY else "timed_out", r[REQ_END])
        for t, open_, busy in tables["samples"]:
            run.add("busy", t, busy * SAMPLE)
            run.add("idle", t, (open_ - busy) * SAMPLE)
            run.add("open", t, open_ * SAMPLE)

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1) + 1):
            refused = run.series("too_many", s, s + 1)[0]
            if refused:
                return [(s + 1.0, f"too many connections: {refused:.0f} refused")]
            waits = [r[REQ_WAIT] for r in run.rows("requests", s, s + 1)]
            if waits and max(waits) >= lab.WAIT_MAX:
                return [(s + 1.0, "requests wait over 1 s for a conn")]
        return []

    def incident_title(self, inc: Incident) -> str:
        return f"{'Slowdown' if inc.kind == 'slowdown' else 'Spike'} #{inc.index + 1}"

    def incident_text(self, inc: Incident, start: bool) -> str:
        if inc.kind == "slowdown":
            return f"is slow: {inc.cause}" if start else "is fast again"
        return f"gets {inc.severity:.0f}x traffic: {inc.cause}" if start else "traffic is back to normal"

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def sample_at(self, run: Run, t: float) -> tuple[int, int]:
        """(open, busy) connections at time t."""
        rows = run.rows("samples", t - 2 * SAMPLE, t + 1e-9)
        return (rows[-1][S_OPEN], rows[-1][S_BUSY]) if rows else (0, 0)

    def waiting_at(self, run: Run, t: float) -> list[tuple]:
        """Requests still waiting for a connection at time t."""
        return [r for r in run.active("requests", t, REQ_END) if r[REQ_START] + r[REQ_WAIT] > t]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        recent = [r for r in run.rows("requests", t - 5, t) if r[REQ_OK]]
        reuse = 1 - sum(r[REQ_NEW] for r in recent) / len(recent) if recent else 1.0

        def reuse_state(v: float) -> str:
            return "bad" if v < lab.REUSE_MIN else "ok"

        def reuse_s(s: int):
            n, new = run.series("served", s, s + 1)[0], run.series("opened", s, s + 1)[0]
            v = 1 - new / n if n else 1.0
            return v, reuse_state(v)

        open_, _ = self.sample_at(run, t)
        refused = run.series("too_many", int(t) - 1, int(t) + 1)

        def conn_state(v: float, errors: float) -> str:
            return "bad" if errors or v >= lab.MAX_CONNECTIONS else "warn" if v > lab.CORES else "ok"

        def conn_s(s: int):
            v = run.series("open", s, s + 1)[0]
            return v, conn_state(v, run.series("too_many", s, s + 1)[0])

        ended = _ended(run, t - 5, t)
        p99 = percentile([r[REQ_WAIT] for r in ended], 99)

        def wait_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.WAIT_MAX else "warn" if v >= 0.25 else "ok"

        def wait_s(s: int):
            v = percentile([r[REQ_WAIT] for r in _ended(run, s, s + 1)], 99)
            return (v or 0.0), wait_state(v)

        tiles = [
            Tile("Reuse", f"{reuse:.0%}", "≥90%", reuse_state(reuse), history(run, t, reuse_s)),
            Tile("Conns", f"{open_}/{lab.MAX_CONNECTIONS}", "<50", conn_state(open_, sum(refused)),
                 history(run, t, conn_s)),
            Tile("p99 wait", fmt_ms(p99), "<1s", wait_state(p99), history(run, t, wait_s)),
        ]
        last = _ended(run, t - 1, t)
        fast = sum(r[REQ_OK] and not r[REQ_NEW] and r[REQ_WAIT] < WAITED for r in last)
        waited = sum(r[REQ_OK] and not r[REQ_NEW] and r[REQ_WAIT] >= WAITED for r in last)
        opened = sum(r[REQ_OK] and r[REQ_NEW] for r in last)
        too_many = sum(r[REQ_FAIL] == TOO_MANY for r in last)
        timed_out = sum(r[REQ_FAIL] == TIMED_OUT for r in last)
        bars = [
            Bar("Users ask", [(run.count("requests", t - 1, t), WHITE)]),
            Bar("Served", [(fast, WHITE), (waited, EXTRA1), (opened, EXTRA2)]),
            Bar("Failed", [(too_many, RED), (timed_out, EXTRA3)]),
        ]
        headline, colour = self._headline(variant, run, t, open_, too_many, timed_out)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title="Requests")

    def _headline(self, variant: str, run: Run, t: float, open_: int, too_many: int, timed_out: int):
        waiting = len(self.waiting_at(run, t))
        if too_many:
            return f"Too many connections: {too_many} refused", RED
        if timed_out:
            return f"Failing fast: {timed_out} gave up waiting", BLUE
        if waiting > 20:
            return f"{waiting} requests wait for a connection", EXTRA2
        inc = self.incident_at(variant, t)
        if inc is not None:
            return ("The database is slow; the pool holds up" if inc.kind == "slowdown"
                    else "Traffic spike; the pool holds up"), BLUE
        return f"Pool: {open_} connections open", MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        partial = _ended(run, s, t)
        served = run.total("served", t) + sum(1 for r in partial if r[REQ_OK])
        failed = run.total("failed", t) + sum(1 for r in partial if not r[REQ_OK])
        waiting = len(self.waiting_at(run, t))
        recent = [r[REQ_END] - r[REQ_START] for r in _ended(run, t - 5, t)]
        return [
            ("served", fmt_int(served), GREEN),
            ("failed", fmt_int(failed), RED if failed else MUTED),
            ("waiting", fmt_int(waiting), EXTRA2 if waiting > 20 else WHITE),
            ("p50", fmt_ms(percentile(recent, 50)), WHITE),
            ("p99", fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("busy", [])), (BLUE, run.hist.get("idle", []))]

    def chart_limit(self):
        return float(lab.MAX_CONNECTIONS), f"{lab.MAX_CONNECTIONS} max"

    def legend_notes(self) -> list[str]:
        return ["The chart: open connections (busy, idle)."]


WORLD = ConnPoolWorld
