"""World for lab kafka_log (Fly.io Gossip Glomers #5)."""

from __future__ import annotations

from labs.kafka_log import lab
from labs.kafka_log.scenario import DUPLICATE, LOST_COMMIT, LOST_WRITE, SEND
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, LIMIT, MUTED, PURPLE, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Stage, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

OP_START, OP_KIND, OP_NODE, OP_KEY, OP_END, OP_OK, OP_BAD = range(7)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
AN_T, AN_KIND, AN_NODE, AN_KEY = range(4)
KV = lab.NODES  # lin-kv's index in the picture and the message table
INF = float("inf")
ANOMALY_NAMES = {DUPLICATE: "duplicate offset", LOST_WRITE: "lost write", LOST_COMMIT: "lost commit"}


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


def _anomalies(kind: int, rule: str, phase: str, fix: str, extra: float = 0.0) -> GoalSpec:
    """A goal that no anomaly of `kind` happens in its window (it alerts at the first one)."""

    def measure(run: Run, inc: Incident, upto: float):
        a, b = WINDOWS[kind](inc)
        n = _count(run, kind, a, min(b, upto))
        return n, str(n)

    return GoalSpec(rule, phase, fix, WINDOWS[kind], measure, lambda v: v == 0,
                    doomed=lambda run, inc, upto: measure(run, inc, upto)[0] > 0, settle_extra=extra)


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
    return v, "–" if v is None else "failed" if v == INF else fmt_ms(v)


GOALS = [
    _anomalies(DUPLICATE, "Offsets unique", "before", "agree on offsets"),
    _anomalies(LOST_WRITE, "No lost writes", "during", "never skip an offset", 1.5),
    _anomalies(LOST_COMMIT, "Commits kept", "after", "share committed offsets", 1.5),
    GoalSpec("Msgs/op < 3", "before", "fewer lin-kv round trips",
             lambda i: (i.t0 - lab.BEFORE, i.t0), _msgs, lambda v: v is not None and v < lab.MSGS_MAX),
    GoalSpec("p99 send < 100ms", "during", "an owner per key",
             lambda i: (i.t0, i.t1), _p99, lambda v: v is not None and v < lab.P99_MAX, settle_extra=1.5),
]


class KafkaLogWorld(World):
    id = "kafka_log"
    title = "Kafka log (Gossip Glomers #5)"
    files = ("labs/kafka_log/main.py",)
    view = "cluster"
    stages = [Stage(label, story, colour, nxt) for (label, story, nxt), colour
              in zip(lab.STAGES, (RED, EXTRA2, BLUE))]
    legend = [(BLUE, "node", "◉"), (PURPLE, "lin-kv", "◉"), (RED, "anomaly", "◉"), (WHITE, "client request"),
              (BLUE, "node message"), (EXTRA1, "lin-kv message"), (LIMIT, "limit", "┄")]
    incident_name = "Incident"
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
        return f"{'Hot key' if inc.kind == 'burst' else 'Slow lin-kv'} #{inc.index + 1}"

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "burst":
            return "BURST" if start else "CALM"
        return "SLOW" if start else "FAST"

    def hot_key(self, run: Run, inc: Incident) -> str:
        k = run.data.get("hot", {}).get(inc.t0)
        return "one key" if k is None else f"k{k}"

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return "traffic is back to normal" if inc.kind == "burst" else "lin-kv is fast again"
        if inc.kind == "burst":
            return f"{inc.severity:.1f}x traffic, mostly sends to one key: {inc.cause}"
        return f"lin-kv answers {inc.severity:.0f}x slower: {inc.cause}"

    def warnings(self, run: Run, inc: Incident):
        slow = next((o[OP_START] for o in run.rows("ops", inc.t0, inc.t1)
                     if o[OP_KIND] == SEND and (not o[OP_OK] or o[OP_END] - o[OP_START] > 3 * lab.P99_MAX)), None)
        return [] if slow is None else [(slow + 0.3, "sends take over 300 ms")]

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
            Tile("Msgs/op", "–" if mpo is None else f"{mpo:.1f}", "<3", msgs_state(mpo), history(run, t, msgs_s)),
            Tile("p99", "failed" if p99 == INF else fmt_ms(p99), "<100ms", p99_state(p99),
                 history(run, t, p99_s)),
            Tile("Anomalies", str(bad), "0", "bad" if bad else "ok", history(run, t, bad_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        kv = sum(1 for m in last if KV in (m[MSG_SRC], m[MSG_DEST]))
        ops = run.count("ops", t - 1, t)
        limit = lab.MSGS_MAX * self.rate
        bars = [Bar("Clients", [(float(ops), WHITE)]),
                Bar("Messages", [(float(len(last) - kv), BLUE), (float(kv), EXTRA1)])]
        recent = run.rows("anomalies", t - 5, t)
        inc = self.incident_at(variant, t)
        if recent:
            x = recent[-1]
            headline, colour = f"{ANOMALY_NAMES[x[AN_KIND]].capitalize()} on k{x[AN_KEY]}!", RED
        elif inc is not None and inc.kind == "burst":
            headline, colour = f"Hot {self.hot_key(run, inc)}: p99 send {fmt_ms(p99)}", EXTRA2
        elif inc is not None:
            headline, colour = f"lin-kv is slow: p99 send {fmt_ms(p99)}", EXTRA2
        else:
            headline, colour = f"Log ok: {'–' if mpo is None else f'{mpo:.1f}'} msgs per operation", MUTED
        return Traffic(tiles, bars, limit, "3 msgs/op", headline, colour, title="Traffic",
                       top=max(limit * 1.5, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("ops", 0.0)
        partial = [o for o in run.rows("ops", s - span - 1, t) if s <= o[OP_END] < t]
        served = run.total("served", t) + sum(1 for o in partial if o[OP_OK])
        failed = run.total("failed", t) + sum(1 for o in partial if not o[OP_OK])
        waiting = len(run.active("ops", t, OP_END))
        recent = [o[OP_END] - o[OP_START] for o in run.rows("ops", t - 5 - span, t) if t - 5 <= o[OP_END] < t]
        return [
            ("served", fmt_int(served), GREEN),
            ("failed", fmt_int(failed), RED if failed else MUTED),
            ("waiting", fmt_int(waiting), WHITE),
            ("p50", fmt_ms(percentile(recent, 50)), WHITE),
            ("p99", fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("peer", [])), (EXTRA1, run.hist.get("kv", []))]

    def chart_limit(self):
        return lab.MSGS_MAX * self.rate, "3/op"

    def legend_notes(self) -> list[str]:
        return ["Dots slowed down to be seen (cosmetic)."]


WORLD = KafkaLogWorld
