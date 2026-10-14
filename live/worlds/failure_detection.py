"""World for lab failure_detection (heartbeats, phi accrual, SWIM). Its words are in
labs/failure_detection/text/<lang>.py."""

from __future__ import annotations

import math

from core.i18n import strings
from labs.failure_detection import lab
from labs.failure_detection.scenario import DEAD, FAILED, SUSPECT
from live.canvas import BLUE, EXTRA1, EXTRA2, LIMIT, MUTED, ORANGE, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history

MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_INDIRECT = range(5)
VIEW_T, VIEW_MARKS, VIEW_CRASHED = range(3)
DEATH_T, DEATH_OBSERVER, DEATH_PEER, DEATH_FALSE = range(4)
REQ_START, REQ_HOME, REQ_NODE, REQ_END, REQ_OUTCOME, REQ_OK = range(6)
INF = math.inf

_s = strings("failure_detection")  # one of the lab's STRINGS, for the goal measures below


def name(i: int) -> str:
    return f"n{i}"


def view_at(run: Run, t: float) -> tuple | None:
    """The checker's last look at or before t: (time, marks, crashed bitmask)."""
    rows = run.rows("views", t - 1.0, t + 1e-9)
    return rows[-1] if rows else None


def _false(run: Run, a: float, b: float) -> list[tuple]:
    return [d for d in run.rows("deaths", a, b) if d[DEATH_FALSE]]


def _msgs_per_node(run: Run, a: float, b: float) -> float | None:
    if b <= a:
        return None
    return run.count("msgs", a, b) / (b - a) / lab.NODES


# ---------------------------------------------------------------- goals


def _found(run: Run, inc: Incident, victim: int, upto: float) -> float | None:
    """Seconds from the crash until some healthy node declared it dead (None: not yet)."""
    for t, marks, _ in run.rows("views", inc.t0, min(inc.t1, upto) + 1e-9):
        if marks[victim] == DEAD:
            return t - inc.t0
    return None


def _false_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t1 + lab.AFTER


def victim_of(run: Run, inc: Incident) -> int:
    return run.data.get("victims", {}).get(inc.t0, 0)


def _detect_window(inc: Incident) -> tuple[float, float]:
    """The crash itself; an incident that is not a crash is judged at once (nothing to find)."""
    return inc.t0, inc.t1 if inc.kind == "crash" else inc.t0


def _detect(run: Run, inc: Incident, upto: float):
    if inc.kind != "crash":
        return 0.0, _s("no_crash")
    v = _found(run, inc, victim_of(run, inc), upto)
    if v is not None:
        return v, f"{v:.1f}s"
    if upto >= inc.t1:
        return INF, _s("never")
    return None, "–"


def _detect_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return inc.kind == "crash" and upto - inc.t0 > lab.DETECT_MAX and _found(run, inc, victim_of(run, inc), upto) is None


def _false_deaths(run: Run, inc: Incident, upto: float):
    a, b = _false_window(inc)
    n = len(_false(run, a, min(b, upto)))
    return n, str(n)


def _msgs(run: Run, inc: Incident, upto: float):
    v = _msgs_per_node(run, max(0.0, inc.t0 - lab.BEFORE), min(inc.t0, upto))
    return v, "–" if v is None else f"{v:.1f}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _detect_window, _detect, lambda v: v is not None and v <= lab.DETECT_MAX,
             doomed=_detect_doomed, settle_extra=0.5, key="detect"),
    GoalSpec("", "during", "", _false_window, _false_deaths, lambda v: v is not None and v <= lab.FALSE_MAX,
             doomed=lambda run, inc, upto: _false_deaths(run, inc, upto)[0] > lab.FALSE_MAX,
             settle_extra=0.5, key="false"),
    GoalSpec("", "before", "", lambda i: (i.t0 - lab.BEFORE, i.t0), _msgs,
             lambda v: v is not None and v < lab.MSGS_MAX, settle_extra=1.0, key="msgs"),
]


class FailureWorld(World):
    id = "failure_detection"
    view = "cluster"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "alive", "◉"), (ORANGE, "suspect", "◉"), (RED, "dead", "◉"), (MUTED, "crashed", "◉"),
              (BLUE, "probe"), (EXTRA1, "indirect"), (RED, "dropped"), (LIMIT, "limit", "┄")]
    incident_verbs = ("crash", "back")
    tables = {
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "views": Table(sort=VIEW_T, times=(VIEW_T,)),
        "deaths": Table(sort=DEATH_T, times=(DEATH_T,)),
        "reqs": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
    }
    chart_top = 0.0

    goals = GOALS

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.victims: dict[float, int] = {}  # incident start -> the node it hits
        self.cuts: dict[float, list[int]] = {}  # incident start -> the nodes a partial partition cuts it from

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 30.0))

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        self.victims.update(piece.get("victims", {}))  # before the incidents' words are written
        self.cuts.update(piece.get("cut", {}))
        self.runs[variant].data.setdefault("victims", {}).update(piece.get("victims", {}))
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for m in tables["msgs"]:
            run.add("msgs", m[MSG_SENT])
            kind = "dropped" if m[MSG_ARRIVED] is None else "indirect" if m[MSG_INDIRECT] else "direct"
            run.add(kind, m[MSG_SENT])
        for r in tables["reqs"]:
            run.add("failed" if r[REQ_OUTCOME] == FAILED else "served", r[REQ_END])
        for d in tables["deaths"]:
            if d[DEATH_FALSE]:
                run.add("false", d[DEATH_T])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def node_name(self, inc: Incident) -> str:
        return name(self.victims.get(inc.t0, 0))

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        words = {"crash": ("crash", "back"), "slow": ("slow", "fast"), "lossy": ("lossy", "clean"),
                 "partial": ("cut", "healed")}[inc.kind]
        return self.word(words[0 if start else 1])

    def incident_text(self, inc: Incident, start: bool) -> str:
        node = self.node_name(inc)
        if not start:
            key = {"crash": "back", "slow": "fast", "lossy": "clean", "partial": "healed"}[inc.kind]
            return self.s(key, node=node)
        if inc.kind == "partial":
            peers = ", ".join(name(j) for j in self.cuts.get(inc.t0, []))
            return self.s("cut_off", node=node, peers=peers, cause=self.cause(inc))
        if inc.kind == "lossy":
            return self.s("lossy", node=node, share=inc.severity, cause=self.cause(inc))
        if inc.kind == "slow":
            return self.s("slowed", node=node, x=inc.severity, cause=self.cause(inc))
        return self.s("crashed", node=node, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        wrong = _false(run, inc.t0, _false_window(inc)[1])
        if not wrong:
            return []
        nodes = sorted({d[DEATH_PEER] for d in wrong})
        return [(wrong[0][DEATH_T], self.s("warn_false", nodes=", ".join(name(j) for j in nodes)))]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        false10 = len(_false(run, t - 10, t))

        def false_s(s: int):
            n = run.series("false", s, s + 1)[0]
            return n, "bad" if n else "ok"

        found = self._last_found(run, t)

        def found_s(s: int):
            v = self._last_found(run, s + 1)
            if v is None:
                return 0.0, "idle"
            return min(v, 5.0), "ok" if v <= lab.DETECT_MAX else "bad"

        msgs = _msgs_per_node(run, max(0.0, t - 5), t)

        def msgs_s(s: int):
            v = run.series("msgs", s, s + 1)[0] / lab.NODES
            return v, "ok" if v < lab.MSGS_MAX * 0.8 else "warn" if v < lab.MSGS_MAX else "bad"

        if found is None:
            found_text, found_state = "–", "idle"
        elif found == INF:
            found_text, found_state = self.s("never"), "bad"
        else:
            found_text, found_state = f"{found:.1f}s", "ok" if found <= lab.DETECT_MAX else "bad"
        msgs_state = "idle" if msgs is None else "ok" if msgs < lab.MSGS_MAX * 0.8 else "warn" if msgs < lab.MSGS_MAX else "bad"
        tiles = [
            Tile(self.s("tile_found"), found_text, f"≤{lab.DETECT_MAX:g}s", found_state, history(run, t, found_s)),
            Tile(self.s("tile_false"), str(false10), "=0", "bad" if false10 else "ok", history(run, t, false_s)),
            Tile(self.s("tile_msgs"), "–" if msgs is None else f"{msgs:.1f}", f"<{lab.MSGS_MAX:g}", msgs_state,
                 history(run, t, msgs_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        indirect = sum(1 for m in last if m[MSG_ARRIVED] is not None and m[MSG_INDIRECT])
        reqs = run.count("reqs", t - 1, t)
        limit = lab.MSGS_MAX * lab.NODES
        bars = [Bar(self.s("bar_clients"), [(float(reqs), WHITE)]),
                Bar(self.s("bar_nodes"), [(float(len(last) - dropped - indirect), BLUE), (float(indirect), EXTRA1),
                                          (float(dropped), RED)])]
        headline, colour = self._headline(variant, run, t)
        return Traffic(tiles, bars, limit, self.s("limit"), headline, colour, title=self.s("messages"),
                       top=max(limit * 1.5, (len(last) + reqs) * 1.05))

    def _last_found(self, run: Run, t: float) -> float | None:
        """How long the latest crash that started before t took to find (INF: never; None: no crash yet)."""
        inc = next((i for i in reversed(run.incidents) if i.kind == "crash" and i.t0 < t), None)
        if inc is None:
            return None
        v = _found(run, inc, self.victims.get(inc.t0, 0), t)
        if v is None:
            return INF if t >= inc.t1 or t - inc.t0 > lab.DETECT_MAX else None
        return v

    def _headline(self, variant: str, run: Run, t: float):
        wrong = _false(run, t - 5, t)
        inc = self.incident_at(variant, t)
        if wrong:
            return self.s("head_false", node=name(wrong[-1][DEATH_PEER])), RED
        if inc is not None and inc.kind == "crash":
            node = name(self.victims.get(inc.t0, 0))
            v = _found(run, inc, self.victims.get(inc.t0, 0), t)
            if v is None:
                return self.s("head_unfound", node=node, s=t - inc.t0), RED
            return self.s("head_found", node=node, s=v), BLUE
        view = view_at(run, t)
        suspects = [i for i, m in enumerate(view[VIEW_MARKS]) if m == SUSPECT] if view else []
        if inc is not None:
            node = name(self.victims.get(inc.t0, 0))
            return self.s(f"head_{inc.kind}", node=node), ORANGE if suspects else MUTED
        if suspects:
            return self.s("head_suspect", node=name(suspects[0])), ORANGE
        return self.s("head_ok"), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "reqs", REQ_START, REQ_END, REQ_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("direct", [])), (EXTRA1, run.hist.get("indirect", [])),
                (RED, run.hist.get("dropped", []))]

    def chart_limit(self):
        return lab.MSGS_MAX * lab.NODES, self.s("chart_limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = FailureWorld
