"""World for lab chain_replication. Its words are in labs/chain_replication/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.chain_replication import lab
from labs.chain_replication.scenario import CLIENT_TIMEOUT, GET, PUT
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, LIMIT, MUTED, ORANGE, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_ms, history, percentile,
)

OP_START, OP_KIND, OP_KEY, OP_VALUE, OP_END, OP_OK, OP_STALE, OP_LOST, OP_NODE = range(9)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_KIND = range(5)
ST_T, ST_CHAIN, ST_DOWN, ST_JOINING, ST_BEHIND, ST_SLOW, ST_INFLIGHT, ST_SENT = range(8)
LOST_T, LOST_KEY, LOST_VALUE = range(3)

SLOW_WRITE = 0.5  # a write acknowledged after this long is slow (orange on the chart)
DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

_s = strings("chain_replication")  # one of the lab's STRINGS, for the goal measures below


def _ended(run: Run, a: float, b: float, upto: float, kind: int) -> list[tuple]:
    """Operations of one kind that started in [a, b) and ended by `upto`."""
    return [o for o in run.rows("ops", a, min(b, upto)) if o[OP_KIND] == kind and o[OP_END] <= upto]


def _p99(writes: list[tuple]) -> float | None:
    return percentile([o[OP_END] - o[OP_START] for o in writes], 99)


def _down_second(run: Run, s: int, upto: float) -> bool | None:
    """Did fewer than 90% of the writes started in second s succeed? None: no writes."""
    writes = _ended(run, s, s + 1, upto, PUT)
    if not writes:
        return None
    return sum(1 for o in writes if o[OP_OK]) / len(writes) < lab.OUTAGE_SHARE


# ---------------------------------------------------------------- goals


def _stale_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t1


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t0


def _stale(run: Run, inc: Incident, upto: float):
    n = sum(1 for o in _ended(run, *_stale_window(inc), upto, GET) if o[OP_STALE])
    return n, str(n)


def _lost(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    n = run.count("lost", a, min(b, upto))
    return n, str(n)


def _outage(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    end = min(b, upto - CLIENT_TIMEOUT) if upto < b + CLIENT_TIMEOUT else b
    n = sum(1 for s in range(int(a), int(end)) if _down_second(run, s, upto))
    return n, _s("seconds", n=n)


def _replicas(run: Run, inc: Incident, upto: float):
    rows = run.rows("state", inc.t1 + lab.AFTER - 1.0, min(inc.t1 + lab.AFTER, upto) + 1e-9)
    if not rows:
        return None, "–"
    n = in_sync(rows[-1])
    return n, f"{n}/{lab.NODES}"


def _p99_goal(run: Run, inc: Incident, upto: float):
    v = _p99(_ended(run, *_before(inc), min(upto, inc.t0), PUT))  # writes caught in the incident are not counted
    return v, fmt_ms(v)


def in_sync(st: tuple) -> int:
    """Replicas in the chain, alive, holding every write acknowledged over a second ago."""
    return sum(1 for i in st[ST_CHAIN] if not (st[ST_DOWN] >> i & 1) and not st[ST_BEHIND][i])


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _stale_window, _stale, lambda v: v is not None and v <= lab.STALE_MAX,
             doomed=lambda run, inc, upto: _stale(run, inc, upto)[0] > lab.STALE_MAX,
             settle_extra=lab.SETTLE, key="stale"),
    GoalSpec("", "during", "", _after, _lost, lambda v: v is not None and v <= lab.LOST_MAX,
             doomed=lambda run, inc, upto: _lost(run, inc, upto)[0] > lab.LOST_MAX,
             settle_extra=lab.SETTLE, key="lost"),
    GoalSpec("", "during", "", _after, _outage, lambda v: v is not None and v <= lab.OUTAGE_MAX,
             doomed=lambda run, inc, upto: _outage(run, inc, upto)[0] > lab.OUTAGE_MAX,
             settle_extra=lab.SETTLE, key="outage"),
    GoalSpec("", "after", "", lambda i: (i.t1, i.t1 + lab.AFTER), _replicas,
             lambda v: v is not None and v >= lab.NODES, settle_extra=0.5, key="replicas"),
    GoalSpec("", "before", "", _before, _p99_goal, lambda v: v is not None and v <= lab.P99_MAX,
             settle_extra=lab.SETTLE, key="p99"),
]


class ChainWorld(World):
    id = "chain_replication"
    view = "pipeline"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(WHITE, "request"), (BLUE, "write"), (GREEN, "ack"), (EXTRA1, "copy"),
              (BLUE, "in_sync", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "behind", "◉"), (ORANGE, "slow", "◉"),
              (RED, "down", "◉"), (LIMIT, "limit", "┄"), (DOWN_KEY, "incident", "█")]
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT,)),
        "state": Table(sort=ST_T, times=(ST_T,)),
        "lost": Table(sort=LOST_T, times=(LOST_T,)),
    }
    goals = GOALS
    chart_top = 15.0

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
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
            if o[OP_KIND] == PUT:
                key = "w_failed" if not o[OP_OK] else "w_slow" if o[OP_END] - o[OP_START] > SLOW_WRITE else "w_ok"
                run.add(key, o[OP_START])
            elif o[OP_STALE]:
                run.add("stale", o[OP_END])
        for r in tables["lost"]:
            run.add("lost", r[LOST_T])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def node_name(self, inc: Incident) -> str:
        return f"n{self.victims.get(inc.t0, 1)}"

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.word("join")
        return self.word("slow" if inc.kind == "slow" else "crash")

    def incident_text(self, inc: Incident, start: bool) -> str:
        node = self.node_name(inc)
        if not start:
            return self.s("back", node=node)
        return self.s(f"{inc.kind}_start", node=node, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        node = self.node_name(inc)
        out = []
        if inc.kind == "slow":
            out.append((inc.t0 + lab.EJECT, self.s("warn_ejected", node=node)))
        else:
            out.append((inc.t0 + lab.DETECT, self.s("warn_dropped", node=node)))
        lost = run.rows("lost", *_after(inc))
        if lost:
            out.append((lost[0][LOST_T], self.s("warn_lost", n=len(lost))))
        stale = sum(1 for o in run.rows("ops", inc.t1, inc.t1 + lab.AFTER) if o[OP_STALE])
        if stale:
            out.append((inc.t1 + lab.AFTER, self.s("warn_stale_after", n=stale, node=node)))
        return out

    # ---------------------------------------------------------------- what the pictures ask

    def state_at(self, variant: str, t: float) -> tuple | None:
        """The checker's last look at the nodes, at or before t."""
        run = self.runs.get(variant)
        if run is None:
            return None
        rows = run.rows("state", t - 1.0, t + 1e-9)
        return rows[-1] if rows else None

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def situation(self, variant: str, t: float, short: bool = False) -> tuple[str, tuple[int, int, int]]:
        """What the chain is going through right now, in a phrase (a word or two with `short`), and its
        colour."""
        key, values, colour = self._situation(variant, t)
        if key == "healthy":
            return self.screen.STATES["healthy"], colour
        return self.s(("short_" if short else "sit_") + key, **values), colour

    def _situation(self, variant: str, t: float) -> tuple[str, dict, tuple[int, int, int]]:
        run = self.runs[variant]
        st = self.state_at(variant, t)
        recent = [o for o in run.rows("ops", t - 2.0 - CLIENT_TIMEOUT, t + 1e-9) if t - 2.0 <= o[OP_END] <= t]
        if run.count("lost", t - 2.0, t + 1e-9):
            return "lost", {}, RED
        if any(o[OP_STALE] for o in recent):
            return "stale", {}, RED
        if st is not None:
            down = [i for i in st[ST_CHAIN] if st[ST_DOWN] >> i & 1]
            if down:
                return "down", {"node": f"n{down[0]}"}, RED
            if st[ST_SLOW] >= 0 and st[ST_SLOW] in st[ST_CHAIN]:
                return "slow", {"node": f"n{st[ST_SLOW]}"}, ORANGE
        writes = [o for o in recent if o[OP_KIND] == PUT]
        if writes and sum(1 for o in writes if not o[OP_OK]) > len(writes) * (1 - lab.OUTAGE_SHARE):
            return "stalled", {"n": st[ST_INFLIGHT] if st is not None else 0}, RED
        if st is not None and st[ST_JOINING]:
            i = next(i for i in range(lab.NODES) if st[ST_JOINING] >> i & 1)
            return "copying", {"node": f"n{i}"}, EXTRA1
        if st is not None and len(st[ST_CHAIN]) < lab.NODES:
            return "short", {"n": len(st[ST_CHAIN]), "of": lab.NODES}, EXTRA2
        return "healthy", {}, GREEN

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = CLIENT_TIMEOUT

        def ended(a: float, b: float, kind: int) -> list[tuple]:
            return [o for o in run.rows("ops", a - span, b) if a <= o[OP_END] < b and o[OP_KIND] == kind]

        stale = int(sum(run.series("stale", int(t) - 10, int(t))))
        lost = int(run.total("lost", t))

        def stale_s(s: int):
            n = run.series("stale", s, s + 1)[0]
            return n, "bad" if n else "ok"

        def lost_s(s: int):
            n = run.series("lost", s, s + 1)[0]
            return n, "bad" if n else "ok"

        def share_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v >= 0.99 else "warn" if v >= lab.OUTAGE_SHARE else "bad"

        def writes_ok(a: float, b: float) -> float | None:
            w = ended(a, b, PUT)
            return sum(1 for o in w if o[OP_OK]) / len(w) if w else None

        def writes_s(s: int):
            v = writes_ok(s, s + 1)
            return (v or 0.0), share_state(v)

        ok = writes_ok(t - 5, t)
        tiles = [
            Tile(self.s("tile_stale"), str(stale), "=0", "bad" if stale else "ok", history(run, t, stale_s)),
            Tile(self.s("tile_lost"), str(lost), "=0", "bad" if lost else "ok", history(run, t, lost_s)),
            Tile(self.s("tile_writes"), "–" if ok is None else f"{ok:.0%}", "≥90%", share_state(ok),
                 history(run, t, writes_s)),
        ]
        w = ended(t - 1, t, PUT)
        r = ended(t - 1, t, GET)
        fast = sum(1 for o in w if o[OP_OK] and o[OP_END] - o[OP_START] <= SLOW_WRITE)
        slow = sum(1 for o in w if o[OP_OK]) - fast
        st = self.state_at(variant, t)
        bars = [
            Bar(self.s("bar_writes"), [(float(fast), WHITE), (float(slow), EXTRA2),
                                       (float(len(w) - fast - slow), RED)]),
            Bar(self.s("bar_reads"), [(float(sum(1 for o in r if o[OP_OK] and not o[OP_STALE])), WHITE),
                                      (float(sum(1 for o in r if o[OP_STALE])), RED),
                                      (float(sum(1 for o in r if not o[OP_OK])), MUTED)]),
        ]
        headline, colour = self.situation(variant, t)
        if colour == GREEN and st is not None:
            headline, colour = self.s("head_chain", chain=" → ".join(f"n{i}" for i in st[ST_CHAIN])), MUTED
        return Traffic(tiles, bars, self.rate / 2, self.s("limit"), headline, colour, title=self.s("title"),
                       top=self.rate * 1.5)

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("w_ok", [])), (EXTRA2, run.hist.get("w_slow", [])),
                (RED, run.hist.get("w_failed", []))]

    def chart_limit(self):
        return self.rate / 2, self.s("limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = ChainWorld
