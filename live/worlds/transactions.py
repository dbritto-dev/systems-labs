"""World for lab transactions (Fly.io Gossip Glomers #6). Its words are in labs/transactions/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.transactions import lab
from labs.transactions.scenario import TXN_END, TXN_OK, TXN_START
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, MUTED, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history

MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
ANOM_T, ANOM_NODE, ANOM_KEY, ANOM_VALUE = range(4)


def fresh(run: Run, a: float, b: float) -> float | None:
    """Share of keys, over every node and sample in [a, b), within 1 s of the newest value."""
    rows = run.rows("stale", a, b)
    if not rows:
        return None
    return 1 - sum(sum(r[1]) for r in rows) / (len(rows) * lab.NODES * lab.KEYS)


_s = strings("transactions")  # one of the lab's STRINGS, for the goal measures below


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
    return float(n), _s("none") if n == 0 else _s("seen", n=n)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


# The rule and fix of each goal are text.GOALS[key]. Intermediate reads are counted from 15 s
# before to 5 s after the partition, and judged after it.
GOALS = [
    GoalSpec("", "before", "", _before, _fresh,
             lambda v: v is not None and v >= lab.FRESH_MIN, settle_extra=lab.BEFORE[1], key="fresh"),
    GoalSpec("", "during", "", _during, _available,
             lambda v: v is not None and v >= lab.AVAILABLE_MIN, settle_extra=2.0, key="answered"),
    GoalSpec("", "after", "", _after, _caught_up,
             lambda v: v is not None and v >= lab.CAUGHT_UP_MIN, key="caught_up"),
    GoalSpec("", "after", "", _around, _g1b, lambda v: v is not None and v <= lab.G1B_MAX,
             doomed=lambda run, inc, upto: _g1b(run, inc, upto)[0] > lab.G1B_MAX, key="g1b"),
]


def _stale_colour(stale: int) -> tuple[int, int, int]:
    if stale == 0:
        return BLUE
    return EXTRA1 if stale <= 5 else EXTRA2 if stale <= 20 else EXTRA3


class TxnWorld(World):
    id = "transactions"
    view = "cluster"
    stage_colours = (RED, EXTRA2, EXTRA1, BLUE)
    legend = [(BLUE, "up_to_date", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "behind", "◉"), (RED, "g1b_read", "◉"),
              (WHITE, "transaction"), (BLUE, "replication"), (RED, "dropped"), (RED, "partition", "┆")]
    incident_verbs = ("split", "heal")
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
        return self.s("cut_off", cause=self.cause(inc)) if start else self.s("whole_again")

    def warnings(self, run: Run, inc: Incident):
        first = run.rows("anomalies", inc.t0 - lab.AROUND[0], inc.t1 + lab.AROUND[1])
        if first:
            a = first[0]
            return [(a[ANOM_T], self.s("warn_g1b", node=a[ANOM_NODE], which=a[ANOM_KEY]))]
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
            Tile(self.s("tile_fresh"), "–" if now_fresh is None else f"{now_fresh:.0%}", "≥95%",
                 fresh_state(now_fresh), history(run, t, fresh_s)),
            Tile(self.s("tile_g1b"), str(g1b), "0", "bad" if g1b else "ok", history(run, t, g1b_s)),
            Tile(self.s("tile_answers"), "–" if answered is None else f"{answered:.0%}", "≥99%",
                 answered_state(answered), history(run, t, answered_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        txns = run.count("txns", t - 1, t)
        bars = [Bar(self.s("bar_clients"), [(float(txns), WHITE)]),
                Bar(self.s("bar_nodes"), [(float(len(last) - dropped), BLUE), (float(dropped), RED)])]
        cut = self.cut_at(variant, t)
        if run.count("anomalies", t - 2, t):
            headline, colour = self.s("head_g1b"), RED
        elif cut is not None:
            headline, colour = self.s("head_cut", node=cut), RED
        elif now_fresh is not None and now_fresh < 0.999:
            headline, colour = self.s("head_behind", fresh=now_fresh), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("messages"),
                       top=max(1.0, (len(last) + txns) * 1.1))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "txns", TXN_START, TXN_END, TXN_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("delivered", [])), (RED, run.hist.get("dropped", []))]

    def chart_limit(self):
        return None

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = TxnWorld
