"""World for lab replication_lag. Its words are in labs/replication_lag/text/<lang>.py."""

from __future__ import annotations

from labs.replication_lag import lab, scenario
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, LIMIT, MUTED, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_ms, history

READ_START, READ_SESSION, READ_NODE, READ_END, READ_OK, READ_RYW, READ_MONO, READ_GAP = range(8)
WRITE_T, WRITE_SESSION, WRITE_OWN, WRITE_LSN = range(4)  # then the delay to each replica
LAG_T, LAG_BEHIND, LAG_UP = range(3)


# ---------------------------------------------------------------- goals


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _reads(run: Run, inc: Incident, upto: float) -> list[tuple]:
    a, b = _window(inc)
    return [r for r in run.rows("reads", a, min(b, upto)) if r[READ_OK] and r[READ_END] <= upto]


def _counter(col: int):
    def measure(run: Run, inc: Incident, upto: float):
        rows = _reads(run, inc, upto)
        if not rows:
            return None, "–"
        n = sum(1 for r in rows if r[col])
        return n, str(n)

    def doomed(run: Run, inc: Incident, upto: float) -> bool:
        return any(r[col] for r in _reads(run, inc, upto))

    return measure, doomed


_ryw, _ryw_doomed = _counter(READ_RYW)
_mono, _mono_doomed = _counter(READ_MONO)


def _primary(run: Run, inc: Incident, upto: float):
    rows = _reads(run, inc, upto)
    if not rows:
        return None, "–"
    v = sum(1 for r in rows if r[READ_NODE] == 0) / len(rows)
    return v, f"{v:.0%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _window, _ryw, lambda v: v == 0, doomed=_ryw_doomed, settle_extra=0.5, key="ryw"),
    GoalSpec("", "during", "", _window, _mono, lambda v: v == 0, doomed=_mono_doomed, settle_extra=0.5,
             key="mono"),
    GoalSpec("", "during", "", _window, _primary, lambda v: v is not None and v <= lab.PRIMARY_MAX,
             settle_extra=0.5, key="primary"),
]

VERBS = {"behind": ("lag", "caught"), "restart": ("down", "up"), "spike": ("spike", "calm")}


def _behind_colour(lag: float) -> tuple[int, int, int]:
    if lag < 0.5:
        return BLUE
    return EXTRA1 if lag < 2 else EXTRA2 if lag < 5 else EXTRA3


class ReplicationLagWorld(World):
    id = "replication_lag"
    view = "fanout"  # opens with the fanout picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "fresh", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "behind", "◉"), (RED, "down", "◉"),
              (WHITE, "read"), (BLUE, "replication"), (RED, "wrong"), (LIMIT, "limit", "┄")]
    tables = {
        "reads": Table(sort=READ_START, times=(READ_START, READ_END)),
        "writes": Table(sort=WRITE_T, times=(WRITE_T,)),
        "lag": Table(sort=LAG_T, times=(LAG_T,)),
    }
    goals = GOALS
    incident_verbs = ("lag", "caught")

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 200.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["reads"]:
            run.add("served" if r[READ_OK] else "failed", r[READ_END])
            if not r[READ_OK]:
                continue
            run.add("primary" if r[READ_NODE] == 0 else "replica", r[READ_START])
            if r[READ_RYW] or r[READ_MONO]:
                run.add("wrong", r[READ_START])
            if r[READ_RYW]:
                run.add("ryw", r[READ_START])
            if r[READ_MONO]:
                run.add("mono", r[READ_START])
        for w in tables["writes"]:
            run.add("writes", w[WRITE_T])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(VERBS.get(inc.kind, VERBS["behind"])[0 if start else 1])

    def incident_title(self, inc: Incident) -> str:
        name = {"restart": self.s("title_restart"), "spike": self.s("title_spike")}.get(inc.kind, self.incident_name)
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        name = scenario.NAMES_OF[scenario.target(inc)]
        if inc.kind == "restart":
            return self.s("restarts", name=name, cause=self.cause(inc)) if start else self.s("back", name=name)
        if inc.kind == "spike":
            return self.s("spike", cause=self.cause(inc)) if start else self.s("spike_over")
        return self.s("behind", name=name, lag=inc.severity, cause=self.cause(inc)) if start \
            else self.s("caught_up", name=name)

    def warnings(self, run: Run, inc: Incident):
        out = []
        a, b = _window(inc)
        for col, key in ((READ_RYW, "warn_ryw"), (READ_MONO, "warn_mono")):
            first = next((r for r in run.rows("reads", a, b) if r[col]), None)
            if first is not None:
                out.append((first[READ_START], self.s(key)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def lag_at(self, run: Run, t: float) -> tuple[tuple[float, ...], tuple[bool, ...]]:
        """Seconds behind, and up or not, for each replica at t."""
        rows = run.rows("lag", t - 0.5, t + 1e-9)
        if not rows:
            return (0.0,) * lab.REPLICAS, (True,) * lab.REPLICAS
        return rows[-1][LAG_BEHIND], rows[-1][LAG_UP]

    def node_colours(self, run: Run, t: float) -> list[tuple[int, int, int]]:
        lags, ups = self.lag_at(run, t)
        return [BLUE] + [_behind_colour(lag) if up else RED for lag, up in zip(lags, ups)]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        recent = [r for r in run.rows("reads", t - 5, t) if r[READ_OK]]
        ryw = sum(1 for r in recent if r[READ_RYW])
        mono = sum(1 for r in recent if r[READ_MONO])
        share = sum(1 for r in recent if r[READ_NODE] == 0) / len(recent) if recent else 0.0

        def count_s(name: str):
            def s_(s: int):
                v = run.series(name, s, s + 1)[0]
                return v, "bad" if v else "ok"
            return s_

        def share_state(v: float) -> str:
            return "bad" if v > lab.PRIMARY_MAX else "warn" if v > lab.PRIMARY_MAX / 2 else "ok"

        def share_s(s: int):
            p, r = run.series("primary", s, s + 1)[0], run.series("replica", s, s + 1)[0]
            v = p / (p + r) if p + r else 0.0
            return v, share_state(v)

        tiles = [
            Tile(self.s("tile_ryw"), str(ryw), "=0", "bad" if ryw else "ok", history(run, t, count_s("ryw"))),
            Tile(self.s("tile_mono"), str(mono), "=0", "bad" if mono else "ok", history(run, t, count_s("mono"))),
            Tile(self.s("tile_primary"), f"{share:.0%}", f"≤{lab.PRIMARY_MAX:.0%}", share_state(share),
                 history(run, t, share_s)),
        ]
        last = [r for r in run.rows("reads", t - 1, t) if r[READ_OK]]
        wrong = sum(1 for r in last if r[READ_RYW] or r[READ_MONO])
        on_primary = sum(1 for r in last if r[READ_NODE] == 0)
        writes = run.count("writes", t - 1, t)
        bars = [Bar(self.s("bar_replicas"), [(float(len(last) - on_primary - wrong), WHITE), (float(wrong), RED)]),
                Bar(self.s("bar_primary"), [(float(on_primary), WHITE)]),
                Bar(self.s("bar_writes"), [(float(writes), BLUE)])]
        reads_rate = self.rate * (1 - scenario.WRITE_SHARE)
        limit = lab.PRIMARY_MAX * reads_rate
        headline, colour = self._headline(variant, run, t, ryw + mono)
        return Traffic(tiles, bars, limit, f"{lab.PRIMARY_MAX:.0%}", headline, colour, title=self.s("reads"),
                       top=max(reads_rate * 1.1, len(last) * 1.05))

    def _headline(self, variant: str, run: Run, t: float, wrong: int):
        lags, ups = self.lag_at(run, t)
        if wrong:
            return self.s("head_wrong", n=wrong), RED
        inc = self.incident_at(variant, t)
        if inc is not None:
            name = scenario.NAMES_OF[scenario.target(inc)]
            if inc.kind == "restart":
                return self.s("head_down", name=name), EXTRA2
            if inc.kind == "spike":
                return self.s("head_spike", lag=max(lags)), EXTRA2
            return self.s("head_behind", name=name, lag=lags[scenario.target(inc) - 1]), EXTRA2
        return self.s("head_ok", lag=fmt_ms(max(lags) or None)), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "reads", READ_START, READ_END, READ_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("replica", [])), (EXTRA2, run.hist.get("primary", [])),
                (RED, run.hist.get("wrong", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note")]

    def state_at(self, variant: str, t: float) -> tuple[str, tuple[int, int, int]]:
        """The words under the grid: which replica is in trouble, and how far behind."""
        words = self.screen.STATES
        run = self.runs.get(variant)
        inc = self.incident_at(variant, t)
        if run is None or inc is None:
            return words["healthy"], GREEN
        lags, ups = self.lag_at(run, t)
        if inc.kind == "spike":
            return f"{words['degraded']}  {max(lags):.1f} s", EXTRA2
        i = scenario.target(inc) - 1
        name = scenario.NAMES_OF[i + 1]
        if not ups[i]:
            return f"{name}  {words['down']}", RED
        return f"{name}  {words['degraded']}  {lags[i]:.1f} s", EXTRA2


WORLD = ReplicationLagWorld
