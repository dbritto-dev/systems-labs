"""World for lab paxos_consensus. Its words are in labs/paxos_consensus/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.paxos_consensus import lab
from labs.paxos_consensus.scenario import (
    ACCEPT, ACCEPTED, DECIDE, DOWN, LEADER, PAUSED, PREPARE, PROMISE, PROPOSE,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, PURPLE, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, history,
)

OP_START, OP_VALUE, OP_END, OP_OK, OP_NODE, OP_KEPT = range(6)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_KIND = range(5)
ST_TIME, ST_ROLES, ST_BALLOTS, ST_DECIDED = range(4)
EV_TIME, EV_SLOT, EV_NODE, EV_KIND = range(4)
INF = float("inf")
PHASE1 = (PREPARE, PROMISE)
PHASE2 = (ACCEPT, ACCEPTED)
RECENT = 2.0  # seconds a disagreement keeps its node red


_s = strings("paxos_consensus")  # one of the lab's STRINGS, for the goal measures below


def name(i: int) -> str:
    return f"n{i}"


def _victims(run: Run, inc: Incident) -> list[int]:
    return run.data.setdefault("victims", {}).get(inc.t0, [])


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE[0], inc.t0 - lab.BEFORE[1]


def _whole(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE[0], inc.t1 + lab.AFTER


def _live_window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def state_at(run: Run, t: float):
    """The latest (time, roles, ballots, decided) the checker saw at or before t."""
    rows = run.rows("state", t - 1.0, t + 1e-9)
    return rows[-1] if rows else None


def leader_at(run: Run, t: float) -> tuple[int | None, int]:
    """The live leader with the highest ballot, and that ballot (or the highest ballot known)."""
    row = state_at(run, t)
    if row is None:
        return None, 0
    leaders = [i for i, r in enumerate(row[ST_ROLES]) if r == LEADER]
    if not leaders:
        return None, max(row[ST_BALLOTS])
    best = max(leaders, key=lambda i: row[ST_BALLOTS][i])
    return best, row[ST_BALLOTS][best]


# ---------------------------------------------------------------- goals


def _ops(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    return [o for o in run.rows("ops", a, min(b, upto)) if o[OP_END] <= upto]


def _disagree(run: Run, a: float, b: float) -> int:
    return sum(1 for e in run.rows("events", a, b))


def _agree(run: Run, inc: Incident, upto: float):
    a, b = _whole(inc)
    n = _disagree(run, a, min(b, upto))
    return n, _s("split_n", n=n)


def _lost(run: Run, inc: Incident, upto: float):
    ops = _ops(run, *_whole(inc), upto)
    n = sum(1 for o in ops if not o[OP_KEPT])
    return n, _s("lost_n", n=n)


def _live(run: Run, inc: Incident, upto: float):
    ops = _ops(run, *_live_window(inc), upto)
    if not ops:
        return NO_VALUE
    v = sum(1 for o in ops if o[OP_OK]) / len(ops)
    return v, f"{v:.0%}"


def _live_doomed(run: Run, inc: Incident, upto: float) -> bool:
    a, b = _live_window(inc)
    failed = sum(1 for o in _ops(run, a, b, upto) if not o[OP_OK])
    expected = max(run.count("ops", a, min(b, upto)), 1)
    return failed / max(expected, (b - a) * 5) > 1 - lab.LIVE_MIN


def cost(run: Run, a: float, b: float) -> float | None:
    """Messages between nodes per decided command, for commands and messages in [a, b)."""
    done = sum(1 for o in run.rows("ops", a, b) if o[OP_OK])
    sent = run.count("msgs", a, b)
    if not done:
        return INF if sent else None
    return sent / done


def _cheap(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    if upto < b:
        return NO_VALUE
    v = cost(run, a, b)
    if v is None:
        return NO_VALUE
    return v, "∞" if v == INF else f"{v:.1f}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "after", "", _whole, _agree, lambda v: v == 0,
             lambda run, inc, upto: _disagree(run, _whole(inc)[0], upto) > 0, settle_extra=1.0, key="agree"),
    GoalSpec("", "after", "", _whole, _lost, lambda v: v == 0,
             lambda run, inc, upto: _lost(run, inc, upto)[0] > 0, settle_extra=lab.DEADLINE + 1.0, key="kept"),
    GoalSpec("", "after", "", _live_window, _live, at_least(lab.LIVE_MIN),
             _live_doomed, settle_extra=lab.DEADLINE + 1.0, key="live"),
    GoalSpec("", "before", "", _before, _cheap, at_most(lab.COST_MAX),
             settle_extra=lab.DEADLINE + 1.0, key="cheap"),
]


class PaxosWorld(World):
    id = "paxos_consensus"
    view = "peers"  # the five nodes on a pentagon, the links between them, and the clients
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(GREEN, "leader", "◉"), (BLUE, "node", "◉"), (EXTRA2, "candidate", "◉"), (RED, "split", "◉"),
              (MUTED, "down", "◉"), (EXTRA3, "paused", "◉"), (WHITE, "request"), (PURPLE, "propose"), (EXTRA1, "phase1"),
              (BLUE, "phase2"), (GREEN, "decide"), (RED, "dropped")]
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT,)),
        "state": Table(sort=ST_TIME, times=(ST_TIME,)),
        "events": Table(sort=EV_TIME, times=(EV_TIME,)),
    }
    goals = GOALS

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._hit: dict[float, list[int]] = {}

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 10.0))

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece) -> None:
        # Who each incident hit, before its events are written.
        self.runs[variant].data.setdefault("victims", {}).update(piece.get("victims", {}))
        self._hit.update(piece.get("victims", {}))
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for m in tables["msgs"]:
            kind = m[MSG_KIND]
            if m[MSG_ARRIVED] is None:
                run.add("dropped", m[MSG_SENT])
            elif kind in PHASE1:
                run.add("phase1", m[MSG_SENT])
            elif kind in PHASE2:
                run.add("phase2", m[MSG_SENT])
            elif kind == DECIDE:
                run.add("decide", m[MSG_SENT])
            elif kind == PROPOSE:
                run.add("propose", m[MSG_SENT])
            else:
                run.add("other", m[MSG_SENT])
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
            if not o[OP_KEPT]:
                run.add("lost", o[OP_END])
        for e in tables["events"]:
            run.add("split", e[EV_TIME])

    def incident_verb(self, inc: Incident, start: bool) -> str:
        verbs = {"proposer_crash": ("crash", "back"), "acceptor_crash": ("crash", "back"),
                 "lossy": ("lossy", "clean"), "partition": ("split", "heal"), "duel": ("pause", "wake")}
        return self.word(verbs[inc.kind][0 if start else 1])

    def incident_text(self, inc: Incident, start: bool) -> str:
        hit = self._hit.get(inc.t0, [])
        node = name(hit[0] if hit else 0)
        cause = self.cause(inc)
        if inc.kind == "proposer_crash":
            return self.s("crashed_mid", node=node, cause=cause) if start else self.s("restarted", node=node)
        if inc.kind == "acceptor_crash":
            return self.s("crashed", node=node, cause=cause) if start else self.s("restarted", node=node)
        if inc.kind == "partition":
            other = name(hit[1] if len(hit) > 1 else 1)
            return self.s("cut_off", node=node, other=other, cause=cause) if start else self.s("whole")
        if inc.kind == "duel":
            return self.s("paused", node=node, cause=cause) if start else self.s("woke", node=node)
        return self.s("lossy", pct=round(inc.severity * 100), cause=cause) if start else self.s("clean")

    def warnings(self, run: Run, inc: Incident):
        out = []
        split = _disagree(run, inc.t0, inc.t1 + lab.AFTER)
        if split:
            out.append((inc.t1, self.s("warn_split", n=split)))
        lost = sum(1 for o in run.rows("ops", inc.t0, inc.t1) if not o[OP_KEPT])
        if lost:
            out.append((inc.t1, self.s("warn_lost", n=lost)))
        return out

    def groups_at(self, variant: str, t: float) -> list[int] | None:
        inc = self.incident_at(variant, t)
        if inc is None or inc.kind != "partition":
            return None
        hit = _victims(self.runs[variant], inc)
        return [1 if i in hit else 0 for i in range(lab.NODES)] if hit else None

    def roles_at(self, variant: str, t: float) -> tuple[int, ...]:
        row = state_at(self.runs[variant], t)
        return row[ST_ROLES] if row else (0,) * lab.NODES

    def split_nodes(self, run: Run, t: float) -> set[int]:
        """Nodes that decided a value another node decided differently, in the last RECENT seconds."""
        return {e[EV_NODE] for e in run.rows("events", t - RECENT, t + 1e-9)}

    def lost_recently(self, run: Run, t: float, span: float = RECENT) -> bool:
        longest = run.max_dur.get("ops", 0.0)
        return any(not o[OP_KEPT] and t - span <= o[OP_END] <= t
                   for o in run.rows("ops", t - span - longest, t + 1e-9))

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        leader, ballot = leader_at(run, t)
        split = int(run.total("split", t) + _disagree(run, int(t), t))
        longest = run.max_dur.get("ops", 0.0)
        lost = int(run.total("lost", t) + sum(1 for o in run.rows("ops", int(t) - longest, t)
                                              if not o[OP_KEPT] and int(t) <= o[OP_END] < t))
        recent = cost(run, t - 5, t)

        def count_s(key: str):
            def fn(s: int):
                v = run.series(key, s, s + 1)[0]
                return v, "bad" if v else "ok"
            return fn

        def cost_s(s: int):
            v = cost(run, s - 4, s + 1)
            if v is None:
                return 0.0, "idle"
            return min(v, 4 * lab.COST_MAX), "bad" if v > lab.COST_MAX else "ok"

        cost_text = "–" if recent is None else "∞" if recent == INF else f"{recent:.1f}"
        tiles = [
            Tile(self.s("tile_split"), str(split), "=0", "bad" if split else "ok", history(run, t, count_s("split"))),
            Tile(self.s("tile_lost"), str(lost), "=0", "bad" if lost else "ok", history(run, t, count_s("lost"))),
            Tile(self.s("tile_cost"), cost_text, f"≤{lab.COST_MAX:.0f}",
                 "idle" if recent is None else "bad" if recent > lab.COST_MAX else "ok", history(run, t, cost_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        delivered = [m[MSG_KIND] for m in last if m[MSG_ARRIVED] is not None]
        p1 = sum(1 for k in delivered if k in PHASE1)
        p2 = sum(1 for k in delivered if k in PHASE2)
        dec = sum(1 for k in delivered if k == DECIDE)
        prop = sum(1 for k in delivered if k == PROPOSE)
        other = len(delivered) - p1 - p2 - dec - prop
        ops = run.count("ops", t - 1, t)
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_nodes"), [(float(prop), PURPLE), (float(p1), EXTRA1), (float(p2), BLUE),
                                          (float(dec), GREEN), (float(other), MUTED), (float(dropped), RED)])]
        inc = self.incident_at(variant, t)
        hit = _victims(run, inc) if inc else []
        splits = run.rows("events", t - RECENT, t + 1e-9)
        if splits:
            headline, colour = self.s("head_split", slot=splits[-1][EV_SLOT]), RED
        elif leader is not None and inc is not None and hit and leader not in hit and inc.kind != "lossy":
            headline, colour = self.s("head_hit", node=name(hit[0]), leader=name(leader), ballot=ballot), EXTRA2
        elif leader is not None:
            headline, colour = self.s("head_leader", leader=name(leader), ballot=ballot), MUTED
        elif p1:
            headline, colour = self.s("head_duel", ballot=ballot), EXTRA2
        else:
            headline, colour = self.s("head_first"), EXTRA2
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("messages"),
                       top=max(self.rate * lab.COST_MAX, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(PURPLE, run.hist.get("propose", [])), (EXTRA1, run.hist.get("phase1", [])), (BLUE, run.hist.get("phase2", [])),
                (GREEN, run.hist.get("decide", [])), (MUTED, run.hist.get("other", [])),
                (RED, run.hist.get("dropped", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = PaxosWorld
ROLE_COLOURS = {0: BLUE, 1: EXTRA2, LEADER: GREEN, DOWN: MUTED, PAUSED: EXTRA3}
