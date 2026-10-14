"""World for lab load_balancing. Its words are in labs/load_balancing/text/<lang>.py."""

from __future__ import annotations

from labs.load_balancing import lab
from labs.load_balancing.scenario import BALANCERS, REPORT, SAMPLE, SERVERS, WORKERS
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, PURPLE, RED, RGB, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_ms, history, percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_BALANCER, REQ_SERVER, REQ_SICK = range(7)
S_T, S_SICK, S_SLOW, S_LOADS = range(4)
SICK_T0, SICK_T1, SICK_SERVER = range(3)
INCIDENT_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
WARN_TIMEOUTS = 3  # timeouts in one second that make a warning
HERD = 0.6  # a balancer sending this share of its last REPORT seconds to one server is herding


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Requests that ended in [a, b)."""
    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b]


def _latency(r: tuple, upto: float) -> float:
    """How long a request took, or has waited so far if it is still waiting at `upto`."""
    return min(r[REQ_END], upto) - r[REQ_START]


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


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _share(run: Run, inc: Incident, upto: float):
    """The share of the requests started during the incident that were sent to the slow server."""
    rows = run.rows("requests", inc.t0, min(inc.t1, upto))
    if not rows:
        return None, "–"
    v = sum(r[REQ_SICK] for r in rows) / len(rows)
    return v, f"{v:.1%}"


def _p99(run: Run, inc: Incident, upto: float):
    """p99 latency of the requests started during the incident (still waiting: counted so far)."""
    cut = min(inc.t1 + lab.SETTLE, upto)
    v = percentile([_latency(r, cut) for r in run.rows("requests", inc.t0, min(inc.t1, upto))], 99)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _served(run: Run, inc: Incident, upto: float):
    """The share of the requests started during the incident that were answered (not timed out)."""
    rows = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_END] <= upto]
    if not rows:
        return None, "–"
    v = sum(r[REQ_OK] for r in rows) / len(rows)
    return v, f"{v:.1%}"


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER_WINDOW


def _recovered(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    cut = min(b + lab.SETTLE, upto)
    rows = run.rows("requests", a, min(b, upto))
    if not rows:
        return None, "–"
    good = sum(r[REQ_OK] and r[REQ_END] - r[REQ_START] < lab.P99_MAX and r[REQ_END] <= cut for r in rows)
    v = good / len(rows)
    return v, f"{v:.0%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, key="baseline"),
    GoalSpec("", "during", "", _during, _share,
             lambda v: v is not None and v <= lab.SHARE_MAX, key="share"),
    GoalSpec("", "during", "", _during, _p99,
             lambda v: v is not None and v < lab.P99_MAX, settle_extra=lab.SETTLE, key="p99"),
    GoalSpec("", "during", "", _during, _served,
             lambda v: v is not None and v >= lab.SERVED_MIN, settle_extra=lab.SETTLE, key="served"),
    GoalSpec("", "after", "", _after, _recovered,
             lambda v: v is not None and v >= lab.RECOVERED_MIN, settle_extra=lab.SETTLE, key="recovered"),
]


class LoadBalancingWorld(World):
    id = "load_balancing"
    view = "cluster"  # where each request goes is the lesson: 4 balancers, 8 servers
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "request"), ([EXTRA1, EXTRA2, EXTRA3], "waits", "●"),
              (GREEN, "served"), (RED, "timed_out"), (BLUE, "server", "◉"), (PURPLE, "slow_server", "◉"),
              (LIMIT, "fair", "┄"), (INCIDENT_KEY, "incident", "█")]
    incident_verbs = ("slow", "fast")
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "samples": Table(sort=S_T, times=(S_T,)),
        "sick": Table(sort=SICK_T0, times=(SICK_T0, SICK_T1)),
    }
    goals = GOALS
    chart_top = 40.0

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 250.0))

    @property
    def fair(self) -> float:
        """Requests per second each server gets when they are spread evenly."""
        return self.rate * lab.FAIR

    # ---------------------------------------------------------------- incidents

    def server_of(self, run: Run, inc: Incident) -> int:
        """The server an incident hits."""
        rows = run.rows("sick", inc.t0 - 1e-6, inc.t0 + 1e-6)
        return rows[0][SICK_SERVER] if rows else 0

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "slow":
            return self.word("slow" if start else "fast")
        return self.word("cold" if start else "warm")

    def incident_title(self, inc: Incident) -> str:
        name = self.s("slow_server" if inc.kind == "slow" else "cold_server")
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def _add_incident_events(self, run: Run, inc: Incident) -> None:
        run.data.setdefault("servers", {})[inc.index] = self.server_of(run, inc)
        super()._add_incident_events(run, inc)

    def incident_text(self, inc: Incident, start: bool) -> str:
        run = next((r for r in self.runs.values() if inc in r.incidents), None)
        n = run.data.get("servers", {}).get(inc.index, 0) if run else 0
        if inc.kind == "slow":
            if start:
                return self.s("is_slow", server=n, times=inc.severity, cause=self.cause(inc))
            return self.s("fast_again", server=n)
        if start:
            return self.s("is_cold", server=n, times=inc.severity, cause=self.cause(inc))
        return self.s("warm_again", server=n)

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def sick_at(self, run: Run, t: float) -> int:
        """The slow server at time t, or -1."""
        rows = run.rows("samples", t - 2 * SAMPLE, t + 1e-9)
        return rows[-1][S_SICK] if rows else -1

    def loads_at(self, run: Run, t: float) -> tuple[int, ...]:
        """Requests in flight on each server at time t (queued or running)."""
        rows = run.rows("samples", t - 2 * SAMPLE, t + 1e-9)
        return rows[-1][S_LOADS] if rows else (0,) * SERVERS

    def herding(self, run: Run, t: float) -> list[float]:
        """For each balancer: the largest share of its requests in the last REPORT seconds sent to one server."""
        picks = [[0] * SERVERS for _ in range(BALANCERS)]
        for r in run.rows("requests", t - REPORT, t + 1e-9):
            picks[r[REQ_BALANCER]][r[REQ_SERVER]] += 1
        return [max(p) / sum(p) if sum(p) >= 8 else 0.0 for p in picks]

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("ask", r[REQ_START])
            run.add(f"to{r[REQ_SERVER]}", r[REQ_START])
            if r[REQ_SICK]:
                run.add("to_sick", r[REQ_START])
            if r[REQ_OK]:
                run.add("served", r[REQ_END])
            else:
                run.add("failed", r[REQ_END])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1) + 1):
            failed = run.series("failed", s, s + 1)[0]
            if failed >= WARN_TIMEOUTS:
                return [(s + 1.0, self.s("warn_timeouts", n=failed))]
        return []

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        sick = self.sick_at(run, t)

        def share_s(s: int):
            n, bad = run.series("ask", s, s + 1)[0], run.series("to_sick", s, s + 1)[0]
            v = bad / n if n else 0.0
            return v, "bad" if v > lab.SHARE_MAX else "warn" if v > lab.SHARE_MAX / 2 else "ok"

        recent = run.rows("requests", t - 5, t)
        if sick >= 0 and recent:
            share = sum(r[REQ_SICK] for r in recent) / len(recent)
            v, state = share, "bad" if share > lab.SHARE_MAX else "warn" if share > lab.SHARE_MAX / 2 else "ok"
            share_text = f"{v:.0%}"
        else:
            share_text, state = "–", "idle"

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.FAST else "ok"

        def p99_s(s: int):
            v = percentile([r[REQ_END] - r[REQ_START] for r in _ended(run, s, s + 1)], 99)
            return (v or 0.0), p99_state(v)

        ended = _ended(run, t - 5, t)
        p99 = percentile([r[REQ_END] - r[REQ_START] for r in ended], 99)

        def served_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.SERVED_MIN else "ok"

        def served_s(s: int):
            ok, bad = run.series("served", s, s + 1)[0], run.series("failed", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else None
            return (1 - v if v is not None else 0.0), served_state(v)

        served = sum(r[REQ_OK] for r in ended) / len(ended) if ended else None
        tiles = [
            Tile(self.s("tile_share"), share_text, f"≤{lab.SHARE_MAX:.0%}", state, history(run, t, share_s)),
            Tile(self.screen.STATS["p99"], fmt_ms(p99), f"<{fmt_ms(lab.P99_MAX)}", p99_state(p99), history(run, t, p99_s)),
            Tile(self.s("tile_served"), "–" if served is None else f"{served:.1%}", f"≥{lab.SERVED_MIN:.0%}",
                 served_state(served), history(run, t, served_s)),
        ]

        last = run.rows("requests", t - 1, t)
        per = [0] * SERVERS
        timed = [0] * SERVERS
        for r in last:
            per[r[REQ_SERVER]] += 1
            timed[r[REQ_SERVER]] += not r[REQ_OK]
        healthy = [i for i in range(SERVERS) if i != sick]
        busiest = max(healthy, key=per.__getitem__)
        quietest = min(healthy, key=per.__getitem__)

        def bar(label: str, i: int, colour: RGB) -> Bar:
            return Bar(label, [(per[i] - timed[i], colour), (timed[i], RED)])

        bars = [
            bar(self.s("bar_busiest", n=busiest), busiest, WHITE),
            bar(self.s("bar_quietest", n=quietest), quietest, WHITE),
            bar(self.s("bar_slow", n=sick), sick, PURPLE) if sick >= 0 else Bar(self.s("bar_no_slow"), []),
        ]
        headline, colour = self._headline(variant, run, t, sick, per, sum(timed))
        return Traffic(tiles, bars, self.fair, self.s("limit_fair", n=round(self.fair)), headline, colour,
                       title=self.s("toplist"))

    def _headline(self, variant: str, run: Run, t: float, sick: int, per: list[int], timed_out: int):
        if timed_out:
            return self.s("head_timeouts", n=timed_out), RED
        herd = max(self.herding(run, t))
        if herd >= HERD:
            return self.s("head_herding", share=herd), EXTRA2
        if sick >= 0:
            share = per[sick] / max(1, sum(per))
            if share > lab.SHARE_MAX:
                return self.s("head_full_share", n=sick, share=share), EXTRA2
            return self.s("head_avoided", n=sick), BLUE
        return self.s("head_spread", n=SERVERS), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "requests", REQ_START, REQ_END, REQ_OK, t,
                                  busy=WORKERS * SERVERS)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(PURPLE, run.hist.get("to_sick", [])), (RED, run.hist.get("failed", []))]

    def chart_limit(self):
        return self.fair, self.s("limit_fair", n=round(self.fair))

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = LoadBalancingWorld
