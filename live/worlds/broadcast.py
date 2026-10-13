"""World for lab broadcast (Fly.io Gossip Glomers #3). Its words are in labs/broadcast/text/<lang>.py."""

from __future__ import annotations

from core.i18n import lab_text
from labs.broadcast import lab
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_ms, history, percentile,
)

OP_START, OP_KIND, OP_NODE, OP_VALUE, OP_END, OP_OK = range(6)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
INF = float("inf")


def _s(key: str, **values) -> str:
    """One of the lab's STRINGS in the language in use (for the goal measures below)."""
    return lab_text("broadcast").STRINGS[key].format(**values)


def _sent(run: Run) -> dict[int, float]:
    return run.data.setdefault("sent", {})


def _reach(run: Run) -> dict[int, tuple[float, bool]]:
    return run.data.setdefault("reach", {})


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE[0], inc.t0 - lab.BEFORE[1]


def _values(run: Run, a: float, b: float) -> list[int]:
    return [v for v, t in _sent(run).items() if a <= t < b]


def _spread(run: Run, a: float, b: float, upto: float) -> list[float]:
    """For numbers sent in [a, b): seconds until every node had them (inf if not yet / never)."""
    sent, reach = _sent(run), _reach(run)
    out = []
    for v in _values(run, a, min(b, upto)):
        t, ok = reach.get(v, (INF, False))
        out.append(t - sent[v] if ok and t <= upto else INF)
    return out


# ---------------------------------------------------------------- goals


def _reached(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    lat = _spread(run, a, b, max(upto, b))
    if not lat:
        return None, "–"
    v = sum(x < INF for x in lat) / len(lat)
    return v, f"{v:.0%}"


def _survived(run: Run, inc: Incident, upto: float):
    deadline = inc.t1 + lab.AFTER
    sent, reach = _sent(run), _reach(run)
    vs = _values(run, inc.t0, min(inc.t1, upto))
    if not vs:
        return None, "–"
    ok = sum(1 for v in vs if (r := reach.get(v)) and r[1] and r[0] <= min(deadline, upto))
    v = ok / len(vs)
    return v, f"{v:.0%}"


def _msgs_per_op(run: Run, a: float, b: float) -> float | None:
    ops = run.count("ops", a, b)
    return run.count("msgs", a, b) / ops if ops else None


def _msgs(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    v = _msgs_per_op(run, a, min(b, upto))
    return v, "–" if v is None else f"{v:.1f}"


def _latency(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    lat = _spread(run, a, b, max(upto, b + lab.BEFORE[1]))
    if not lat:
        return None, "–"
    p50, top = percentile(lat, 50), max(lat)
    if p50 == INF:
        text = _s("lost")
    else:
        text = f"{p50 * 1000:.0f}/{_s('lost') if top == INF else f'{top * 1000:.0f}ms'}"
    return (p50, top), text


def _fast(limits: tuple[float, float]):
    def ok(v) -> bool:
        return v is not None and v[0] < limits[0] and v[1] < limits[1]
    return ok


def _before(inc: Incident) -> tuple[float, float]:
    return _window(inc)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _reached, lambda v: v is not None and v >= lab.REACH_MIN,
             settle_extra=lab.BEFORE[1], key="reach"),
    GoalSpec("", "after", "", lambda i: (i.t0, i.t1 + lab.AFTER), _survived,
             lambda v: v is not None and v >= lab.REACH_MIN, settle_extra=1.0, key="survive"),
    GoalSpec("", "before", "", _before, _msgs, lambda v: v is not None and v < lab.EFFICIENT_MSGS,
             settle_extra=lab.BEFORE[1], key="msgs30"),
    GoalSpec("", "before", "", _before, _latency, _fast((lab.EFFICIENT_P50, lab.EFFICIENT_MAX)),
             settle_extra=lab.BEFORE[1], key="fast"),
    GoalSpec("", "before", "", _before, _msgs, lambda v: v is not None and v < lab.BATCHED_MSGS,
             settle_extra=lab.BEFORE[1], key="msgs20"),
    GoalSpec("", "before", "", _before, _latency, _fast((lab.BATCHED_P50, lab.BATCHED_MAX)),
             settle_extra=lab.BEFORE[1], key="batched"),
]


class BroadcastWorld(World):
    id = "broadcast"
    view = "cluster"
    stage_colours = (RED, EXTRA3, EXTRA2, EXTRA1, BLUE)
    legend = [(BLUE, "complete", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "missing", "◉"),
              (WHITE, "request"), (BLUE, "message"), (RED, "dropped"),
              (RED, "partition", "┆"), (LIMIT, "limit", "┄")]
    incident_verbs = ("split", "heal")
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "values": Table(sort=0, times=(0,)),
        "done": Table(sort=0, times=(0,)),
        "lag": Table(sort=0, times=(0,)),
    }
    goals = GOALS
    chart_top = 0.0

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 20.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        sent, reach = _sent(run), _reach(run)
        for t, v in tables["values"]:
            sent[v] = t
        for t, v, ok in tables["done"]:
            reach[v] = (t, ok)
        for m in tables["msgs"]:
            run.add("msgs", m[MSG_SENT])
            run.add("delivered" if m[MSG_ARRIVED] is not None else "dropped", m[MSG_SENT])
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
        run.data.setdefault("groups", {}).update(piece.get("groups", {}))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s("whole")
        return self.s("cut_off" if inc.kind == "isolate" else "split", cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        sent, reach = _sent(run), _reach(run)
        stuck = [v for v in _values(run, inc.t0, inc.t1) if not ((r := reach.get(v)) and r[1] and r[0] <= inc.t1)]
        if stuck:
            return [(inc.t1, self.s("warn_stuck", n=len(stuck)))]
        return []

    def groups_at(self, variant: str, t: float) -> list[int] | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        inc = next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)
        if inc is None:
            return None
        groups = run.data.get("groups", {}).get(inc.t0)
        if not groups:
            return None
        out = [0] * lab.NODES
        for g, members in enumerate(groups):
            for i in members:
                out[i] = g
        return out

    def missing_at(self, run: Run, t: float) -> tuple[int, ...]:
        rows = run.rows("lag", t - 0.5, t + 1e-9)
        return rows[-1][1] if rows else (0,) * lab.NODES

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        mpo = _msgs_per_op(run, t - 10, t)

        def msgs_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.EFFICIENT_MSGS else "warn" if v >= lab.BATCHED_MSGS else "ok"

        def msgs_s(s: int):
            o, m = run.series("ops", s, s + 1)[0], run.series("msgs", s, s + 1)[0]
            v = m / o if o else 0.0
            return v, msgs_state(v if o else None)

        done = [x for x in _spread(run, t - 12, t - 2, t) if x < INF]
        p50 = percentile(done, 50)

        def lat_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.EFFICIENT_P50 * 2 else "warn" if v >= lab.EFFICIENT_P50 else "ok"

        def lat_s(s: int):
            xs = [x for x in _spread(run, s - 2, s - 1, s + 1) if x < INF]
            v = percentile(xs, 50)
            return (v or 0.0), lat_state(v)

        sent, reach = _sent(run), _reach(run)
        behind = sum(1 for v in _values(run, t - 30, t) if not ((r := reach.get(v)) and r[1] and r[0] <= t))
        old = sum(1 for v in _values(run, t - 30, t - 5) if not ((r := reach.get(v)) and r[1] and r[0] <= t))

        def behind_s(s: int):
            n = sum(1 for v in _values(run, s - 30, s) if not ((r := reach.get(v)) and r[1] and r[0] <= s))
            late = sum(1 for v in _values(run, s - 30, s - 5) if not ((r := reach.get(v)) and r[1] and r[0] <= s))
            return float(n), "bad" if late else "warn" if n > 10 else "ok"

        tiles = [
            Tile(self.s("tile_msgs"), "–" if mpo is None else f"{mpo:.0f}", "<30", msgs_state(mpo),
                 history(run, t, msgs_s)),
            Tile(self.s("tile_p50"), fmt_ms(p50), "<400ms", lat_state(p50), history(run, t, lat_s)),
            Tile(self.s("tile_behind"), str(behind), "→0", "bad" if old else "warn" if behind > 10 else "ok",
                 history(run, t, behind_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        ops = run.count("ops", t - 1, t)
        limit = lab.EFFICIENT_MSGS * self.rate
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_nodes"), [(float(len(last) - dropped), BLUE), (float(dropped), RED)])]
        groups = self.groups_at(variant, t)
        if groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            headline, colour = self.s("head_split", sizes=" | ".join(map(str, sizes)), n=behind), RED
        elif behind:
            headline, colour = self.s("head_behind", n=behind), EXTRA2
        else:
            headline, colour = self.s("head_ok", p50=fmt_ms(p50)), MUTED
        return Traffic(tiles, bars, limit, self.s("limit"), headline, colour, title=self.s("messages"),
                       top=max(limit * 1.5, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("delivered", [])), (RED, run.hist.get("dropped", []))]

    def chart_limit(self):
        return lab.EFFICIENT_MSGS * self.rate, self.s("chart_limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = BroadcastWorld
