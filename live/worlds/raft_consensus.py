"""World for lab raft_consensus. Its words are in labs/raft_consensus/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.raft_consensus import lab
from labs.raft_consensus.scenario import CANDIDATE, COMMITTED, DOWN, LEADER, LOST, TWO_LEADERS, VOTE
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, RED, WHITE
from live.worlds.base import (
    KEEP, PIECE, Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history,
)

OP_START, OP_VALUE, OP_END, OP_OK, OP_NODE = range(5)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_KIND = range(5)
ST_TIME, ST_ROLES, ST_TERMS = range(3)
INF = float("inf")


_s = strings("raft_consensus")  # one of the lab's STRINGS, for the goal measures below


def name(i: int) -> str:
    return f"n{i}"


def _committed(run: Run) -> dict[int, float]:
    """Command -> when the checker first saw it on a majority."""
    return run.data.setdefault("committed", {})


def _victims(run: Run, inc: Incident) -> list[int]:
    return run.data.setdefault("victims", {}).get(inc.t0, [])


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE[0], inc.t0 - lab.BEFORE[1]


def _leaders(roles) -> list[int]:
    return [i for i, r in enumerate(roles) if r == LEADER]


def state_at(run: Run, t: float):
    """The latest (time, roles, terms) the checker saw at or before t."""
    rows = run.rows("state", t - 1.0, t + 1e-9)
    return rows[-1] if rows else None


def leader_at(run: Run, t: float) -> tuple[int | None, int]:
    """The live leader with the highest term, and that term (or the highest term known)."""
    row = state_at(run, t)
    if row is None:
        return None, 0
    leaders = _leaders(row[ST_ROLES])
    if not leaders:
        return None, max(row[ST_TERMS])
    best = max(leaders, key=lambda i: row[ST_TERMS][i])
    return best, row[ST_TERMS][best]


# ---------------------------------------------------------------- goals


def _has_leader(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    rows = run.rows("state", a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(1 for r in rows if _leaders(r[ST_ROLES])) / len(rows)
    return v, f"{v:.0%}"


def _elected(run: Run, inc: Incident, upto: float) -> float | None:
    """Seconds from the start of the incident until a node it did not hit leads (None: not yet)."""
    hit = set(_victims(run, inc))
    for t, roles, _ in run.rows("state", inc.t0, min(inc.t1 + lab.AFTER, upto)):
        if any(i not in hit for i in _leaders(roles)):
            return t - inc.t0
    return None


def _election(run: Run, inc: Incident, upto: float):
    v = _elected(run, inc, upto)
    if v is not None:
        return v, f"{v:.1f}s"
    if upto >= inc.t1 + lab.AFTER:
        return INF, _s("never")
    return None, "–"


def _election_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return upto - inc.t0 > lab.ELECTION_MAX and _elected(run, inc, upto) is None


def _ops(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    return [o for o in run.rows("ops", a, min(b, upto)) if o[OP_END] <= upto]


def _commits(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    ops = _ops(run, a, b, upto)
    if not ops:
        return None, "–"
    committed = _committed(run)
    stored = [o[OP_OK] and committed.get(o[OP_VALUE], INF) < min(upto, INF) for o in ops]
    good = sum(stored)
    wrong = sum(1 for o, s in zip(ops, stored) if o[OP_OK] and not s)
    v = good / len(ops)
    return (v, wrong), _s("wrong_n", n=wrong) if wrong else f"{v:.1%}"


def _lost(run: Run, a: float, b: float) -> int:
    return sum(1 for e in run.rows("events", a, b) if e[3] in (LOST, TWO_LEADERS))


def _safe(run: Run, inc: Incident, upto: float):
    n = _lost(run, inc.t0, min(inc.t1 + lab.AFTER, upto))
    return n, _s("lost_n", n=n)


def _available(run: Run, inc: Incident, upto: float):
    ops = _ops(run, inc.t0, inc.t1, upto)
    if not ops:
        return None, "–"
    v = sum(1 for o in ops if o[OP_OK]) / len(ops)
    return v, f"{v:.0%}"


def _available_doomed(run: Run, inc: Incident, upto: float) -> bool:
    n = run.count("ops", inc.t0, inc.t1) or 1
    failed = sum(1 for o in _ops(run, inc.t0, inc.t1, upto) if not o[OP_OK])
    return failed / max(n, (inc.t1 - inc.t0) * 5) > 1 - lab.AVAILABLE_MIN


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _has_leader, lambda v: v is not None and v >= lab.LEADER_MIN,
             settle_extra=lab.BEFORE[1], key="leader"),
    GoalSpec("", "after", "", lambda i: (i.t0, i.t1 + lab.AFTER), _election,
             lambda v: v is not None and v < lab.ELECTION_MAX, _election_doomed, key="election"),
    GoalSpec("", "before", "", _before, _commits,
             lambda v: v is not None and v[0] >= lab.COMMITTED_MIN and v[1] == 0,
             settle_extra=lab.BEFORE[1], key="committed"),
    GoalSpec("", "after", "", lambda i: (i.t0, i.t1 + lab.AFTER), _safe, lambda v: v == 0,
             lambda run, inc, upto: _lost(run, inc.t0, upto) > 0, settle_extra=1.0, key="safe"),
    GoalSpec("", "during", "", lambda i: (i.t0, i.t1), _available,
             lambda v: v is not None and v >= lab.AVAILABLE_MIN, settle_extra=lab.SETTLE, key="available"),
]


class RaftWorld(World):
    id = "raft_consensus"
    view = "peers"  # the five nodes on a pentagon, the links between them, and the clients
    stage_colours = (RED, EXTRA3, EXTRA2, BLUE)
    legend = [(GREEN, "leader", "◉"), (BLUE, "follower", "◉"), (EXTRA2, "candidate", "◉"),
              (MUTED, "down", "◉"), (WHITE, "request"), (BLUE, "append"), (EXTRA1, "vote"),
              (RED, "dropped"), (RED, "partition", "✕")]  # a cut link (the cluster view draws a dashed line)
    incident_verbs = ("split", "heal")
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "state": Table(sort=ST_TIME, times=(ST_TIME,)),
        "events": Table(sort=0, times=(0,)),
    }
    goals = GOALS

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece) -> None:
        # Who each incident hit, before its events are written.
        self.runs[variant].data.setdefault("victims", {}).update(piece.get("victims", {}))
        self._hit = piece.get("victims", {})
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        committed = _committed(run)
        old = run.end - KEEP - 2 * PIECE  # commands that old are no longer looked at
        for value in [v for v, t in committed.items() if t < old]:
            del committed[value]
        for t, value, _, kind in tables["events"]:
            if kind == COMMITTED:
                committed.setdefault(value, t)
            elif kind == LOST:
                run.add("lost", t)
        for m in tables["msgs"]:
            if m[MSG_ARRIVED] is None:
                run.add("dropped", m[MSG_SENT])
            else:
                run.add("vote" if m[MSG_KIND] == VOTE else "append", m[MSG_SENT])
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        verbs = {"partition": ("split", "heal"), "crash": ("crash", "back"), "slow": ("slow", "fast")}
        return self.word(verbs[inc.kind][0 if start else 1])

    def incident_text(self, inc: Incident, start: bool) -> str:
        hit = getattr(self, "_hit", {}).get(inc.t0, [])
        if inc.kind == "partition":
            if not start:
                return self.s("whole")
            node, other = (name(i) for i in (hit + [0, 1])[:2])
            return self.s("cut_off", node=node, other=other, cause=self.cause(inc))
        if inc.kind == "crash":
            node = name(hit[0] if hit else 0)
            return self.s("crashed", node=node, cause=self.cause(inc)) if start else self.s("restarted", node=node)
        return self.s("slow", x=inc.severity, cause=self.cause(inc)) if start else self.s("fast")

    def warnings(self, run: Run, inc: Incident):
        out = []
        lost = sum(1 for e in run.rows("events", inc.t0, inc.t1 + 1.0) if e[3] == LOST)
        if lost:
            out.append((inc.t1, self.s("warn_lost", n=lost)))
        committed = _committed(run)
        wrong = sum(1 for o in run.rows("ops", inc.t0, inc.t1)
                    if o[OP_OK] and committed.get(o[OP_VALUE], INF) > inc.t1 + 1.0)
        if wrong:
            out.append((inc.t1, self.s("warn_wrong", n=wrong)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def groups_at(self, variant: str, t: float) -> list[int] | None:
        inc = self.incident_at(variant, t)
        if inc is None or inc.kind != "partition":
            return None
        hit = _victims(self.runs[variant], inc)
        return [1 if i in hit else 0 for i in range(lab.NODES)] if hit else None

    def roles_at(self, variant: str, t: float) -> tuple[int, ...]:
        row = state_at(self.runs[variant], t)
        return row[ST_ROLES] if row else (0,) * lab.NODES

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        leader, term = leader_at(run, t)

        def leader_s(s: int):
            who, _ = leader_at(run, s + 0.99)
            return (1.0, "ok") if who is not None else (0.0, "bad")

        def term_s(s: int):
            row = state_at(run, s + 0.99)
            return (float(max(row[ST_TERMS])), "ok") if row else (0.0, "idle")

        def lost_s(s: int):
            n = run.total("lost", s + 1)
            return float(n), "bad" if n else "ok"

        lost = int(run.total("lost", t) + sum(1 for e in run.rows("events", int(t), t) if e[3] == LOST))
        tiles = [
            Tile(self.s("tile_leader"), "–" if leader is None else name(leader), "1",
                 "ok" if leader is not None else "bad", history(run, t, leader_s)),
            Tile(self.s("tile_term"), str(term), "", "ok", history(run, t, term_s)),
            Tile(self.s("tile_lost"), str(lost), "0", "bad" if lost else "ok", history(run, t, lost_s)),
        ]
        last = run.rows("msgs", t - 1, t)
        dropped = sum(1 for m in last if m[MSG_ARRIVED] is None)
        votes = sum(1 for m in last if m[MSG_ARRIVED] is not None and m[MSG_KIND] == VOTE)
        ops = run.count("ops", t - 1, t)
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_nodes"), [(float(len(last) - dropped - votes), BLUE), (float(votes), EXTRA1),
                                          (float(dropped), RED)])]
        inc = self.incident_at(variant, t)
        hit = _victims(run, inc) if inc else []
        lead = "–" if leader is None else name(leader)
        if leader is None:
            headline, colour = self.s("head_electing", term=term), EXTRA2
        elif inc is not None and inc.kind == "partition" and hit:
            headline, colour = self.s("head_split", node=name(hit[0]), leader=lead, term=term), RED
        elif inc is not None and inc.kind == "crash" and hit:
            headline, colour = self.s("head_down", node=name(hit[0]), leader=lead, term=term), RED
        else:
            headline, colour = self.s("head_ok", leader=lead, term=term), MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("messages"),
                       top=max(50.0, (len(last) + ops) * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("append", [])), (EXTRA1, run.hist.get("vote", [])),
                (RED, run.hist.get("dropped", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = RaftWorld
ROLE_COLOURS = {0: BLUE, CANDIDATE: EXTRA2, LEADER: GREEN, DOWN: MUTED}
