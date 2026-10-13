"""World for lab kafka_log (Fly.io Gossip Glomers #5). Its words are in labs/kafka_log/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.kafka_log import lab
from labs.kafka_log.scenario import DUPLICATE, LOST_COMMIT, LOST_WRITE, SEND
from live.canvas import BLUE, EXTRA1, EXTRA2, LIMIT, MUTED, PURPLE, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_ms, history, percentile,
)

OP_START, OP_KIND, OP_NODE, OP_KEY, OP_END, OP_OK, OP_BAD = range(7)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
AN_T, AN_KIND, AN_NODE, AN_KEY = range(4)
KV = lab.NODES  # lin-kv's index in the picture and the message table
INF = float("inf")
ANOMALY_KEYS = {DUPLICATE: "duplicate", LOST_WRITE: "lost_write", LOST_COMMIT: "lost_commit"}  # STRINGS keys


_s = strings("kafka_log")  # one of the lab's STRINGS, for the goal measures below


def _count(run: Run, kind: int, a: float, b: float) -> int:
    return sum(1 for x in run.rows("anomalies", a, b) if x[AN_KIND] == kind)


def _msgs_per_op(run: Run, a: float, b: float) -> float | None:
    ops = run.count("ops", a, b)
    return run.count("msgs", a, b) / ops if ops else None


def _send_times(run: Run, a: float, b: float, upto: float) -> list[float]:
    """Seconds each send started in [a, b) took (inf if it failed), as known at `upto`."""
    out = []
    for o in run.rows("ops", a, min(b, upto)):
        if o[OP_KIND] != SEND:
            continue
        if o[OP_END] <= upto:
            out.append(o[OP_END] - o[OP_START] if o[OP_OK] else INF)
        elif upto - o[OP_START] > lab.P99_MAX:  # still waiting, already too slow
            out.append(upto - o[OP_START])
    return out


# ---------------------------------------------------------------- goals


def _anomalies(kind: int, key: str, phase: str, extra: float = 0.0) -> GoalSpec:
    """A goal that no anomaly of `kind` happens in its window (it alerts at the first one)."""

    def measure(run: Run, inc: Incident, upto: float):
        a, b = WINDOWS[kind](inc)
        n = _count(run, kind, a, min(b, upto))
        return n, str(n)

    return GoalSpec("", phase, "", WINDOWS[kind], measure, lambda v: v == 0,
                    doomed=lambda run, inc, upto: measure(run, inc, upto)[0] > 0, settle_extra=extra, key=key)


WINDOWS = {
    DUPLICATE: lambda i: (i.t0 - lab.BEFORE, i.t0),
    LOST_WRITE: lambda i: (i.t0, i.t1),
    LOST_COMMIT: lambda i: (i.t1, i.t1 + lab.AFTER),
}


def _msgs(run: Run, inc: Incident, upto: float):
    v = _msgs_per_op(run, inc.t0 - lab.BEFORE, min(inc.t0, upto))
    return v, "–" if v is None else f"{v:.1f}"


def _p99(run: Run, inc: Incident, upto: float):
    v = percentile(_send_times(run, inc.t0, inc.t1, upto), 99)
    return v, "–" if v is None else _s("failed") if v == INF else fmt_ms(v)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    _anomalies(DUPLICATE, "unique", "before"),
    _anomalies(LOST_WRITE, "lost_writes", "during", 1.5),
    _anomalies(LOST_COMMIT, "commits", "after", 1.5),
    GoalSpec("", "before", "", lambda i: (i.t0 - lab.BEFORE, i.t0), _msgs,
             lambda v: v is not None and v < lab.MSGS_MAX, key="msgs"),
    GoalSpec("", "during", "", lambda i: (i.t0, i.t1), _p99,
             lambda v: v is not None and v < lab.P99_MAX, settle_extra=1.5, key="p99"),
]


class KafkaLogWorld(World):
    id = "kafka_log"
    view = "cluster"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "node", "◉"), (PURPLE, "lin_kv", "◉"), (RED, "anomaly", "◉"), (WHITE, "client_request"),
              (BLUE, "node_message"), (EXTRA1, "kv_message"), (LIMIT, "limit", "┄")]
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "anomalies": Table(sort=AN_T, times=(AN_T,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 30.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
        for m in tables["msgs"]:
            run.add("msgs", m[MSG_SENT])
            run.add("kv" if KV in (m[MSG_SRC], m[MSG_DEST]) else "peer", m[MSG_SENT])
        for x in tables["anomalies"]:
            run.add("anomalies", x[AN_T])
        run.data.setdefault("hot", {}).update(piece.get("hot", {}))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_title(self, inc: Incident) -> str:
        name = self.s("title_burst" if inc.kind == "burst" else "title_slowkv")
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "burst":
            return self.word("burst" if start else "calm")
        return self.word("slow" if start else "fast")

    def hot_key(self, run: Run, inc: Incident) -> str:
        k = run.data.get("hot", {}).get(inc.t0)
        return self.s("one_key") if k is None else f"k{k}"

    def anomaly(self, kind: int) -> str:
        """An anomaly's name in words, e.g. "duplicate offset"."""
        return self.s(ANOMALY_KEYS[kind])

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s("burst_end" if inc.kind == "burst" else "slow_end")
        if inc.kind == "burst":
            return self.s("burst_start", severity=inc.severity, cause=self.cause(inc))
        return self.s("slow_start", severity=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        slow = next((o[OP_START] for o in run.rows("ops", inc.t0, inc.t1)
                     if o[OP_KIND] == SEND and (not o[OP_OK] or o[OP_END] - o[OP_START] > 3 * lab.P99_MAX)), None)
        return [] if slow is None else [(slow + 0.3, self.s("warn_slow"))]

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        mpo = _msgs_per_op(run, t - 10, t)

        def msgs_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.MSGS_MAX else "warn" if v >= lab.MSGS_MAX * 0.6 else "ok"

        def msgs_s(s: int):
            o, m = run.series("ops", s, s + 1)[0], run.series("msgs", s, s + 1)[0]
            return (m / o if o else 0.0), msgs_state(m / o if o else None)

        p99 = percentile(_send_times(run, t - 5, t, t), 99)

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.P99_MAX * 0.6 else "ok"

        def p99_s(s: int):
            v = percentile(_send_times(run, s, s + 1, s + 1), 99)
            return (min(v, 2.0) if v is not None else 0.0), p99_state(v)

        bad = sum(1 for _ in run.rows("anomalies", t - 30, t))

        def bad_s(s: int):
            n = run.series("anomalies", s, s + 1)[0]
            return n, "bad" if n else "ok"

        tiles = [
            Tile(self.s("tile_msgs"), "–" if mpo is None else f"{mpo:.1f}", "<3", msgs_state(mpo),
                 history(run, t, msgs_s)),
            Tile(self.s("tile_p99"), self.s("failed") if p99 == INF else fmt_ms(p99), "<100ms", p99_state(p99),
                 history(run, t, p99_s)),
            Tile(self.s("tile_anomalies"), str(bad), "0", "bad" if bad else "ok", history(run, t, bad_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        kv = sum(1 for m in last if KV in (m[MSG_SRC], m[MSG_DEST]))
        ops = run.count("ops", t - 1, t)
        limit = lab.MSGS_MAX * self.rate
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_messages"), [(float(len(last) - kv), BLUE), (float(kv), EXTRA1)])]
        recent = run.rows("anomalies", t - 5, t)
        inc = self.incident_at(variant, t)
        if recent:
            x = recent[-1]
            what = self.anomaly(x[AN_KIND])
            headline, colour = self.s("head_anomaly", what=what[:1].upper() + what[1:], k=f"k{x[AN_KEY]}"), RED
        elif inc is not None and inc.kind == "burst":
            headline, colour = self.s("head_hot", k=self.hot_key(run, inc), p99=fmt_ms(p99)), EXTRA2
        elif inc is not None:
            headline, colour = self.s("head_slow", p99=fmt_ms(p99)), EXTRA2
        else:
            headline, colour = self.s("head_ok", mpo="–" if mpo is None else f"{mpo:.1f}"), MUTED
        return Traffic(tiles, bars, limit, self.s("limit", limit=lab.MSGS_MAX), headline, colour,
                       title=self.s("traffic"), top=max(limit * 1.5, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t, busy=10**9)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("peer", [])), (EXTRA1, run.hist.get("kv", []))]

    def chart_limit(self):
        return lab.MSGS_MAX * self.rate, self.s("chart_limit", limit=lab.MSGS_MAX)

    def legend_notes(self) -> list[str]:
        return [self.s("note_dots")]


WORLD = KafkaLogWorld
