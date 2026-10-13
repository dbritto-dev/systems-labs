"""World for lab txn (Fly.io Gossip Glomers #6)."""

from __future__ import annotations

from labs.txn import lab
from labs.txn.scenario import (
    TXN_END, TXN_OK, TXN_START,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Stage, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
ANOM_T, ANOM_NODE, ANOM_KEY, ANOM_VALUE = range(4)


def fresh(run: Run, a: float, b: float) -> float | None:
    """Share of keys, over every node and sample in [a, b), within 1 s of the newest value."""
    rows = run.rows("stale", a, b)
    if not rows:
        return None
    return 1 - sum(sum(r[1]) for r in rows) / (len(rows) * lab.NODES * lab.KEYS)


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE[0], inc.t0 - lab.BEFORE[1]


def _fresh(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = fresh(run, a, min(b, upto))
    return v, "–" if v is None else f"{v:.0%}"


def _available(run: Run, inc: Incident, upto: float):
    done = [r for r in run.rows("txns", inc.t0, min(inc.t1, upto)) if r[TXN_END] <= upto]
    if not done:
        return None, "–"
    v = sum(r[TXN_OK] for r in done) / len(done)
    return v, f"{v:.0%}"


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.CAUGHT_UP[0], inc.t1 + lab.CAUGHT_UP[1]


def _caught_up(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    v = fresh(run, a, min(b, upto))
    return v, "–" if v is None else f"{v:.0%}"


def _around(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.AROUND[0], inc.t1 + lab.AROUND[1]


def _g1b(run: Run, inc: Incident, upto: float):
    a, b = _around(inc)
    n = run.count("anomalies", a, min(b, upto))
    return float(n), "none" if n == 0 else f"{n} seen"


GOALS = [
    GoalSpec("Fresh ≥ 95%", "before", "replicate every write",
             _before, _fresh, lambda v: v is not None and v >= lab.FRESH_MIN, settle_extra=lab.BEFORE[1]),
    GoalSpec("Answered ≥ 99%", "during", "never wait for a peer",
             lambda i: (i.t0, i.t1), _available, lambda v: v is not None and v >= lab.AVAILABLE_MIN,
             settle_extra=2.0),
    GoalSpec("Caught up ≥ 99%", "after", "re-send until acked",
             _after, _caught_up, lambda v: v is not None and v >= lab.CAUGHT_UP_MIN),
    GoalSpec("No G1b reads", "around", "replicate whole txns",
             _around, _g1b, lambda v: v is not None and v <= lab.G1B_MAX,
             doomed=lambda run, inc, upto: _g1b(run, inc, upto)[0] > lab.G1B_MAX),
]


def _stale_colour(stale: int) -> tuple[int, int, int]:
    if stale == 0:
        return BLUE
    return EXTRA1 if stale <= 5 else EXTRA2 if stale <= 20 else EXTRA3


class TxnWorld(World):
    id = "txn"
    title = "Transactions (Gossip Glomers #6)"
    files = ("labs/txn/main.py",)
    view = "cluster"
    stages = [Stage(label, story, colour, nxt) for (label, story, nxt), colour
              in zip(lab.STAGES, (RED, EXTRA2, EXTRA1, BLUE))]
    legend = [(BLUE, "up to date", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "behind", "◉"), (RED, "G1b read", "◉"),
              (WHITE, "transaction"), (BLUE, "replication"), (RED, "dropped"), (RED, "partition", "┆")]
    incident_name = "Partition"
    incident_verbs = ("SPLIT", "HEAL")
    tables = {
        "txns": Table(sort=TXN_START, times=(TXN_START, TXN_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "anomalies": Table(sort=ANOM_T, times=(ANOM_T,)),
        "stale": Table(sort=0, times=(0,)),
    }
    goals = GOALS

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["txns"]:
            run.add("txns", r[TXN_START])
            run.add("served" if r[TXN_OK] else "failed", r[TXN_END])
        for m in tables["msgs"]:
            run.add("delivered" if m[MSG_ARRIVED] is not None else "dropped", m[MSG_SENT])
        for a in tables["anomalies"]:
            run.add("g1b", a[ANOM_T])
        run.data.setdefault("cut", {}).update(piece.get("cut", {}))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_text(self, inc: Incident, start: bool) -> str:
        return f"a node is cut off: {inc.cause}" if start else "the network is whole again"

    def warnings(self, run: Run, inc: Incident):
        first = run.rows("anomalies", inc.t0 - lab.AROUND[0], inc.t1 + lab.AROUND[1])
        if first:
            a = first[0]
            return [(a[ANOM_T], f"n{a[ANOM_NODE]} showed an intermediate value of key {a[ANOM_KEY]}")]
        return []

    def cut_at(self, variant: str, t: float) -> int | None:
        """The node cut off at time t, if any."""
        run = self.runs.get(variant)
        if run is None:
            return None
        inc = next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)
        return None if inc is None else run.data.get("cut", {}).get(inc.t0)

    def stale_at(self, run: Run, t: float) -> tuple[int, ...]:
        rows = run.rows("stale", t - 0.5, t + 1e-9)
        return rows[-1][1] if rows else (0,) * lab.NODES

    def node_colours(self, run: Run, t: float) -> list:
        colours = [_stale_colour(s) for s in self.stale_at(run, t)]
        for a in run.rows("anomalies", t - 0.5, t + 1e-9):  # an intermediate read flashes red
            colours[a[ANOM_NODE]] = RED
        return colours

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        now_fresh = fresh(run, t - 5, t)

        def fresh_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.FRESH_MIN else "warn" if v < 0.999 else "ok"

        def fresh_s(s: int):
            v = fresh(run, s, s + 1)
            return (v or 0.0), fresh_state(v)

        g1b = run.count("anomalies", t - 30, t)

        def g1b_s(s: int):
            n = run.series("g1b", s, s + 1)[0]
            return n, "bad" if n else "ok"

        done = [r for r in run.rows("txns", t - 5 - run.max_dur.get("txns", 0.0), t) if t - 5 <= r[TXN_END] < t]
        answered = sum(r[TXN_OK] for r in done) / len(done) if done else None

        def answered_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.AVAILABLE_MIN else "ok"

        def answered_s(s: int):
            ok, bad = run.series("served", s, s + 1)[0], run.series("failed", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else None
            return (v or 0.0), answered_state(v)

        tiles = [
            Tile("Fresh", "–" if now_fresh is None else f"{now_fresh:.0%}", "≥95%", fresh_state(now_fresh),
                 history(run, t, fresh_s)),
            Tile("G1b", str(g1b), "0", "bad" if g1b else "ok", history(run, t, g1b_s)),
            Tile("Answers", "–" if answered is None else f"{answered:.0%}", "≥99%", answered_state(answered),
                 history(run, t, answered_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        txns = run.count("txns", t - 1, t)
        bars = [Bar("Clients", [(float(txns), WHITE)]),
                Bar("Nodes", [(float(len(last) - dropped), BLUE), (float(dropped), RED)])]
        cut = self.cut_at(variant, t)
        if run.count("anomalies", t - 2, t):
            headline, colour = "G1b: a reader saw an overwritten value", RED
        elif cut is not None:
            headline, colour = f"n{cut} is cut off: replication waits", RED
        elif now_fresh is not None and now_fresh < 0.999:
            headline, colour = f"Some nodes are behind ({now_fresh:.1%} fresh)", EXTRA2
        else:
            headline, colour = "Every node is up to date", MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title="Messages",
                       top=max(1.0, (len(last) + txns) * 1.1))

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("txns", 0.0)
        partial = [r for r in run.rows("txns", s - span - 1, t) if s <= r[TXN_END] < t]
        served = run.total("served", t) + sum(1 for r in partial if r[TXN_OK])
        failed = run.total("failed", t) + sum(1 for r in partial if not r[TXN_OK])
        waiting = len(run.active("txns", t, TXN_END))
        recent = [r[TXN_END] - r[TXN_START] for r in run.rows("txns", t - 5 - span, t) if t - 5 <= r[TXN_END] < t]
        return [
            ("answered", fmt_int(served), GREEN),
            ("unanswered", fmt_int(failed), RED if failed else MUTED),
            ("waiting", fmt_int(waiting), WHITE),
            ("p50", fmt_ms(percentile(recent, 50)), WHITE),
            ("p99", fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("delivered", [])), (RED, run.hist.get("dropped", []))]

    def chart_limit(self):
        return None

    def legend_notes(self) -> list[str]:
        return ["Chart: replication messages per second."]


WORLD = TxnWorld
