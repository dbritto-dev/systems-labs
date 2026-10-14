"""World for lab vector_clocks_crdts (multi-leader carts). Its words are in labs/vector_clocks_crdts/text/<lang>.py."""

from __future__ import annotations

from labs.vector_clocks_crdts import lab
from labs.vector_clocks_crdts.scenario import BACK, LOST
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, LIMIT, MUTED, ORANGE, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history

OP_START, OP_KIND, OP_NODE, OP_CART, OP_PRODUCT, OP_END, OP_OK, OP_VERDICT = range(8)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)
CONV_T, CONV_SHARE, CONV_BEHIND = range(3)
FOUND_T, FOUND_KIND, FOUND_NODE, FOUND_CART, FOUND_PRODUCT = range(5)


def _found(run: Run, kind: int, a: float, b: float) -> int:
    return sum(1 for f in run.rows("found", a, b) if f[FOUND_KIND] == kind)


def _sync_at(run: Run, t: float) -> tuple[float, tuple[int, ...]] | None:
    rows = run.rows("conv", t - 1.0, t + 1e-9)
    return (rows[-1][CONV_SHARE], rows[-1][CONV_BEHIND]) if rows else None


# ---------------------------------------------------------------- goals


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _counter(kind: int):
    def measure(run: Run, inc: Incident, upto: float):
        a, b = _window(inc)
        n = _found(run, kind, a, min(b, upto))
        return n, str(n)

    return measure


def _in_sync(run: Run, inc: Incident, upto: float):
    got = _sync_at(run, min(inc.t1 + lab.CONVERGE, upto))
    if got is None:
        return None, "–"
    return got[0], f"{got[0]:.0%}"


def _msgs(run: Run, inc: Incident, upto: float):
    a, b = inc.t0 - lab.BEFORE, min(inc.t0, upto)
    if b <= a:
        return None, "–"
    v = run.count("msgs", a, b) / (b - a)
    return v, f"{v:.0f}/s"


_lost, _back = _counter(LOST), _counter(BACK)

# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "after", "", _window, _lost, lambda v: v is not None and v <= lab.LOST_MAX,
             doomed=lambda run, inc, upto: _lost(run, inc, upto)[0] > lab.LOST_MAX, settle_extra=0.5, key="lost"),
    GoalSpec("", "after", "", _window, _back, lambda v: v is not None and v <= lab.BACK_MAX,
             doomed=lambda run, inc, upto: _back(run, inc, upto)[0] > lab.BACK_MAX, settle_extra=0.5, key="back"),
    GoalSpec("", "after", "", lambda i: (i.t1, i.t1 + lab.CONVERGE), _in_sync,
             lambda v: v is not None and v >= lab.SYNC_MIN, settle_extra=0.5, key="sync"),
    GoalSpec("", "before", "", lambda i: (i.t0 - lab.BEFORE, i.t0), _msgs,
             lambda v: v is not None and v <= lab.MSGS_MAX, settle_extra=0.5, key="msgs"),
]


class CartsWorld(World):
    id = "vector_clocks_crdts"
    view = "cluster"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "in_sync", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "diverged", "◉"), (RED, "lost", "◉"),
              (WHITE, "request"), (BLUE, "gossip"), (RED, "dropped"), (LIMIT, "limit", "┄")]
    incident_verbs = ("split", "heal")
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "conv": Table(sort=CONV_T, times=(CONV_T,)),
        "found": Table(sort=FOUND_T, times=(FOUND_T,)),
    }
    goals = GOALS
    chart_top = 0.0

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.groups: dict[float, list[list[int]]] = {}  # incident start -> who can still talk
        self.skews: dict[float, tuple[int, float]] = {}  # incident start -> (replica, seconds off)

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        self.groups.update(piece.get("groups", {}))  # before the incidents' words are written
        self.skews.update(piece.get("skews", {}))
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for m in tables["msgs"]:
            run.add("delivered" if m[MSG_ARRIVED] is not None else "dropped", m[MSG_SENT])
        for o in tables["ops"]:
            run.add("served" if o[OP_OK] else "failed", o[OP_END])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def groups_at(self, variant: str, t: float) -> list[int] | None:
        """During a partition: the group of each replica."""
        inc = self.incident_at(variant, t)
        groups = self.groups.get(inc.t0) if inc is not None else None
        if not groups:
            return None
        out = [0] * lab.NODES
        for g, members in enumerate(groups):
            for i in members:
                out[i] = g
        return out

    def skew_at(self, variant: str, t: float) -> tuple[int, float] | None:
        inc = self.incident_at(variant, t)
        return self.skews.get(inc.t0) if inc is not None else None

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "skew":
            return self.word("skew" if start else "ntp")
        if inc.kind == "offline":
            return self.word("offline" if start else "back")
        return self.word("split" if start else "heal")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if inc.kind == "skew":
            node, off = self.skews.get(inc.t0, (0, 0.0))
            if not start:
                return self.s("ntp_fixed", node=f"n{node}")
            key = "skew_ahead" if off > 0 else "skew_behind"
            return self.s(key, node=f"n{node}", s=abs(off), cause=self.cause(inc))
        groups = self.groups.get(inc.t0, [[0], [1, 2, 3, 4]])
        if inc.kind == "offline":
            node = f"n{groups[0][0]}"
            return self.s("offline", node=node, cause=self.cause(inc)) if start else self.s("online", node=node)
        sides = " | ".join(" ".join(f"n{i}" for i in g) for g in groups)
        return self.s("split", sides=sides, cause=self.cause(inc)) if start else self.s("healed")

    def warnings(self, run: Run, inc: Incident):
        a, b = _window(inc)
        out = []
        lost, back = _found(run, LOST, a, b), _found(run, BACK, a, b)
        if lost:
            out.append((inc.t1, self.s("warn_lost", n=lost)))
        if back:
            out.append((inc.t1, self.s("warn_back", n=back)))
        return out

    def behind_at(self, run: Run, t: float) -> tuple[int, ...]:
        got = _sync_at(run, t)
        return got[1] if got else (0,) * lab.NODES

    def wrong_at(self, run: Run, t: float, span: float = 1.5) -> set[int]:
        """Replicas where an add vanished or a removed item came back in the last `span` seconds."""
        return {f[FOUND_NODE] for f in run.rows("found", t - span, t + 1e-9)}

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        def count_s(kind: int):
            def fn(s: int):
                n = _found(run, kind, s, s + 1)
                return float(n), "bad" if n else "ok"
            return fn

        def share_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v >= 0.99 else "warn" if v >= 0.8 else "bad"

        def sync_s(s: int):
            got = _sync_at(run, s + 1)
            v = got[0] if got else None
            return (v or 0.0), share_state(v)

        lost, back = _found(run, LOST, t - 10, t), _found(run, BACK, t - 10, t)
        sync = _sync_at(run, t)
        share = sync[0] if sync else None
        tiles = [
            Tile(self.s("tile_lost"), str(lost), "=0", "bad" if lost else "ok", history(run, t, count_s(LOST))),
            Tile(self.s("tile_back"), str(back), "=0", "bad" if back else "ok", history(run, t, count_s(BACK))),
            Tile(self.s("tile_sync"), "–" if share is None else f"{share:.0%}", "≥99%", share_state(share),
                 history(run, t, sync_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        ops = run.count("ops", t - 1, t)
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_gossip"), [(float(len(last) - dropped), BLUE), (float(dropped), RED)])]
        groups = self.groups_at(variant, t)
        skew = self.skew_at(variant, t)
        inc = self.incident_at(variant, t)
        if lost:
            headline, colour = self.s("head_lost", n=lost), RED
        elif back:
            headline, colour = self.s("head_back", n=back), RED
        elif groups is not None and inc is not None and inc.kind == "offline":
            headline, colour = self.s("head_offline", node=f"n{self.groups[inc.t0][0][0]}"), ORANGE
        elif groups is not None:
            sizes = sorted((groups.count(g) for g in set(groups)), reverse=True)
            headline, colour = self.s("head_split", sizes=" | ".join(map(str, sizes))), ORANGE
        elif skew is not None:
            key = "head_ahead" if skew[1] > 0 else "head_behind"
            headline, colour = self.s(key, node=f"n{skew[0]}", s=abs(skew[1])), ORANGE
        elif share is not None and share < 1.0:
            headline, colour = self.s("head_sync", share=share), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, lab.MSGS_MAX, self.s("limit"), headline, colour, title=self.s("messages"),
                       top=max(lab.MSGS_MAX * 1.5, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("delivered", [])), (RED, run.hist.get("dropped", []))]

    def chart_limit(self):
        return lab.MSGS_MAX, self.s("chart_limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = CartsWorld
