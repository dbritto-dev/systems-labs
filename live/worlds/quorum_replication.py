"""World for lab quorum_replication (Dynamo-style quorums). Its words are in labs/quorum_replication/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.quorum_replication import lab
from labs.quorum_replication.scenario import CLIENT_TIMEOUT, GET
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, LIMIT, MUTED, ORANGE, PINK, RED, WHITE, YELLOW
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, below, history,
)

OP_START, OP_KIND, OP_NODE, OP_KEY, OP_VALUE, OP_END, OP_OK, OP_STALE = range(8)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
CONV_T, CONV_SHARE, CONV_BEHIND = range(3)

_s = strings("quorum_replication")  # one of the lab's STRINGS, for the goal measures below


def _stale(run: Run, a: float, b: float) -> int:
    return sum(1 for o in run.rows("ops", a, b) if o[OP_STALE])


def _sync_at(run: Run, t: float) -> tuple[float, tuple[int, ...]] | None:
    rows = run.rows("conv", t - 1.0, t + 1e-9)
    return (rows[-1][CONV_SHARE], rows[-1][CONV_BEHIND]) if rows else None


def _msgs_per_op(run: Run, a: float, b: float) -> float | None:
    ops = run.count("ops", a, b)
    return run.count("msgs", a, b) / ops if ops else None


# ---------------------------------------------------------------- goals


def _stale_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t1


def _stale_reads(run: Run, inc: Incident, upto: float):
    a, b = _stale_window(inc)
    n = _stale(run, a, min(b, upto))
    return n, str(n)


def _answered(run: Run, inc: Incident, upto: float):
    ops = [o for o in run.rows("ops", inc.t0, min(inc.t1, upto)) if o[OP_END] <= upto]
    if not ops:
        return NO_VALUE
    v = sum(1 for o in ops if o[OP_OK]) / len(ops)
    return v, f"{v:.0%}"


def _in_sync(run: Run, inc: Incident, upto: float):
    got = _sync_at(run, min(inc.t1 + lab.SYNC_AFTER, upto))
    if got is None:
        return NO_VALUE
    return got[0], f"{got[0]:.0%}"


def _msgs(run: Run, inc: Incident, upto: float):
    v = _msgs_per_op(run, inc.t0 - lab.BEFORE, min(inc.t0, upto))
    return v, "–" if v is None else f"{v:.1f}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _stale_window, _stale_reads, at_most(lab.STALE_MAX),
             doomed=lambda run, inc, upto: _stale_reads(run, inc, upto)[0] > lab.STALE_MAX,
             settle_extra=CLIENT_TIMEOUT + 0.5, key="stale"),
    GoalSpec("", "during", "", lambda i: (i.t0, i.t1), _answered,
             at_least(lab.ANSWERED_MIN), settle_extra=CLIENT_TIMEOUT + 0.5,
             key="answered"),
    GoalSpec("", "after", "", lambda i: (i.t1, i.t1 + lab.SYNC_AFTER), _in_sync,
             at_least(lab.SYNC_MIN), settle_extra=0.5, key="sync"),
    GoalSpec("", "before", "", lambda i: (i.t0 - lab.BEFORE, i.t0), _msgs,
             below(lab.MSGS_MAX), settle_extra=1.0, key="msgs"),
]


class QuorumWorld(World):
    id = "quorum_replication"
    view = "fanout"  # opens with the fanout picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "in_sync", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "behind", "◉"), (RED, "down", "◉"), (PINK, "cut", "◉"), (YELLOW, "slow", "◉"),
              (WHITE, "request"), (BLUE, "message"), (RED, "dropped"), (LIMIT, "limit", "┄")]
    incident_verbs = ("crash", "back")
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "conv": Table(sort=CONV_T, times=(CONV_T,)),
    }
    goals = GOALS
    chart_top = 0.0

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.victims: dict[float, int] = {}  # incident start -> the node it hits

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 20.0))

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        self.victims.update(piece.get("victims", {}))  # before the incidents' words are written
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for m in tables["msgs"]:
            run.add("msgs", m[MSG_SENT])
            run.add("delivered" if m[MSG_ARRIVED] is not None else "dropped", m[MSG_SENT])
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])

    def node_name(self, inc: Incident) -> str:
        return f"n{self.victims.get(inc.t0, 0)}"

    def sick_at(self, variant: str, t: float) -> tuple[int, str] | None:
        """(node, kind) of the incident going on at t, if any."""
        run = self.runs.get(variant)
        if run is None:
            return None
        inc = next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)
        return None if inc is None else (self.victims.get(inc.t0, 0), inc.kind)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "slow":
            return self.word("slow" if start else "fast")
        return self.word(("cut" if inc.kind == "isolate" else "crash") if start else "back")

    def incident_text(self, inc: Incident, start: bool) -> str:
        node = self.node_name(inc)
        if not start:
            return self.s("fast" if inc.kind == "slow" else "back", node=node)
        key = {"slow": "slowed", "isolate": "cut_off"}.get(inc.kind, "crashed")
        return self.s(key, node=node, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        n = _stale(run, inc.t0, inc.t1)
        return [(inc.t1, self.s("warn_stale", n=n))] if n else []

    def behind_at(self, run: Run, t: float) -> tuple[int, ...]:
        got = _sync_at(run, t)
        return got[1] if got else (0,) * lab.NODES

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        stale = _stale(run, t - 10, t)

        def stale_s(s: int):
            n = _stale(run, s, s + 1)
            return float(n), "bad" if n else "ok"

        def answered(a: float, b: float) -> float | None:
            ops = [o for o in run.rows("ops", a - CLIENT_TIMEOUT, b) if a <= o[OP_END] < b]
            return sum(1 for o in ops if o[OP_OK]) / len(ops) if ops else None

        def share_state(v: float | None, bad: float) -> str:
            return "idle" if v is None else "ok" if v >= 0.99 else "warn" if v >= bad else "bad"

        def answered_s(s: int):
            v = answered(s, s + 1)
            return (v or 0.0), share_state(v, 0.9)

        sync = _sync_at(run, t)
        share = sync[0] if sync else None

        def sync_s(s: int):
            got = _sync_at(run, s + 1)
            v = got[0] if got else None
            return (v or 0.0), share_state(v, 0.9)

        ans = answered(t - 5, t)
        tiles = [
            Tile(self.s("tile_stale"), str(stale), "=0", "bad" if stale else "ok", history(run, t, stale_s)),
            Tile(self.s("tile_answered"), "–" if ans is None else f"{ans:.0%}", "≥99%", share_state(ans, 0.9),
                 history(run, t, answered_s)),
            Tile(self.s("tile_sync"), "–" if share is None else f"{share:.0%}", "≥99%",
                 share_state(share, 0.9), history(run, t, sync_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        ops = run.count("ops", t - 1, t)
        limit = lab.MSGS_MAX * self.rate
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_nodes"), [(float(len(last) - dropped), BLUE), (float(dropped), RED)])]
        sick = self.sick_at(variant, t)
        behind = self.behind_at(run, t)
        if sick is not None and sick[1] == "slow":
            headline, colour = self.s("head_slow", node=f"n{sick[0]}"), ORANGE
        elif sick is not None:
            headline, colour = self.s("head_down", node=f"n{sick[0]}", n=behind[sick[0]]), RED
        elif stale:
            headline, colour = self.s("head_stale", n=stale), RED
        elif share is not None and share < 1.0:
            headline, colour = self.s("head_sync", share=share), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, limit, self.s("limit"), headline, colour, title=self.s("messages"),
                       top=max(limit * 1.5, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("delivered", [])), (RED, run.hist.get("dropped", []))]

    def chart_limit(self):
        return lab.MSGS_MAX * self.rate, self.s("chart_limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = QuorumWorld
