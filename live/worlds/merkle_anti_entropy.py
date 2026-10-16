"""World for lab merkle_anti_entropy (replicas that drift, and repair). Its words are in labs/merkle_anti_entropy/text/<lang>.py."""

from __future__ import annotations

import math

from core.i18n import strings
from labs.merkle_anti_entropy import lab
from labs.merkle_anti_entropy.api import HINTS
from labs.merkle_anti_entropy.scenario import READ
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, MUTED, ORANGE, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_most, fmt_int, history,
)

OP_START, OP_KIND, OP_NODE, OP_END, OP_STALE = range(5)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_REPAIR, MSG_ENTRIES = range(6)
ST_T, ST_DIVERGED, ST_HASHED, ST_FIXED = range(4)

_s = strings("merkle_anti_entropy")  # one of the lab's STRINGS, for the goal measures below


def state_at(run: Run, t: float) -> tuple | None:
    """The checker's latest look at the replicas, at or before t."""
    rows = run.rows("state", t - 1.0, t + 1e-9)
    return rows[-1] if rows else None


def diverged_at(run: Run, t: float) -> tuple[int, ...]:
    row = state_at(run, t)
    return row[ST_DIVERGED] if row else (0,) * lab.REPLICAS


def per_key(sent: float, fixed: float) -> float | None:
    """Repair entries sent per key repaired: None when repair sent nothing at all."""
    if fixed:
        return sent / fixed
    return None if sent == 0 else math.inf


# ---------------------------------------------------------------- goals


def _repaired(run: Run, inc: Incident, upto: float):
    rows = run.rows("state", inc.t1 + 0.01, min(inc.t1 + lab.REPAIR_S, upto) + 1e-9)
    for r in rows:
        if sum(r[ST_DIVERGED]) == 0:
            dt = r[ST_T] - inc.t1
            return dt, f"{dt:.1f} s"
    if not rows:
        return NO_VALUE
    return None, _s("left", n=sum(rows[-1][ST_DIVERGED]))


def _stale_window(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.REPAIR_S, inc.t1 + lab.REPAIR_S + lab.STALE_FOR


def _stale(run: Run, inc: Incident, upto: float):
    a, b = _stale_window(inc)
    reads = [o for o in run.rows("ops", a, min(b, upto)) if o[OP_KIND] == READ]
    if not reads:
        return NO_VALUE
    v = sum(1 for o in reads if o[OP_STALE]) / len(reads)
    return v, f"{v:.2%}"


def _sent_window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.REPAIR_S


def _sent(run: Run, inc: Incident, upto: float):
    a, b = _sent_window(inc)
    b = min(b, upto)
    sent = sum(m[MSG_ENTRIES] for m in run.rows("msgs", a, b) if m[MSG_REPAIR])
    fixed = sum(sum(r[ST_FIXED]) for r in run.rows("state", a, b))
    v = per_key(sent, fixed)
    if v is None:
        return NO_VALUE
    return v, _s("per_key", v=v) if v != math.inf else _s("none_fixed", n=sent)


def _hashes(run: Run, inc: Incident, upto: float):
    a, b = inc.t0 - lab.BEFORE, min(inc.t0, upto)
    if b <= a:
        return NO_VALUE
    rows = run.rows("state", a, b)
    v = max(sum(r[ST_HASHED][i] for r in rows) for i in range(lab.REPLICAS)) / (b - a)
    return v, _s("rate", v=v)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "after", "", lambda i: (i.t1, i.t1 + lab.REPAIR_S), _repaired,
             at_most(lab.REPAIR_S), settle_extra=0.5, key="fixed"),
    GoalSpec("", "after", "", _stale_window, _stale, at_most(lab.STALE_MAX),
             settle_extra=0.5, key="stale"),
    GoalSpec("", "after", "", _sent_window, _sent, lambda v: v is None or v <= lab.SENT_MAX,
             settle_extra=0.5, key="sent"),
    GoalSpec("", "before", "", lambda i: (i.t0 - lab.BEFORE, i.t0), _hashes,
             at_most(lab.HASH_MAX), settle_extra=0.5, key="hashes"),
]


def shade(keys: int):
    """A replica's colour: blue when it holds the latest of everything, deeper orange the more it misses."""
    if keys == 0:
        return BLUE
    return EXTRA1 if keys <= 50 else EXTRA2 if keys <= 500 else EXTRA3


class MerkleWorld(World):
    id = "merkle_anti_entropy"
    view = "peers"  # replicas turning orange, and the repair traffic on the links between them, is the lesson
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "in_sync", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "diverged", "◉"), (RED, "down", "◉"),
              (WHITE, "request"), (BLUE, "replication"), (EXTRA2, "repair"), (RED, "dropped")]
    incident_verbs = ("down", "up")
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "state": Table(sort=ST_T, times=(ST_T,)),
    }
    goals = GOALS
    chart_top = 0.0

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.facts: dict[float, dict] = {}  # incident start -> what it did (replica, keys, ...)

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        for t0, fact in piece.get("facts", {}).items():  # before the incidents' words are written
            self.facts.setdefault(t0, {}).update(fact)
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["ops"]:
            run.add("reads" if o[OP_KIND] == READ else "writes", o[OP_START])
            if o[OP_STALE]:
                run.add("stale", o[OP_START])
        for m in tables["msgs"]:
            run.add("repair" if m[MSG_REPAIR] else "replication", m[MSG_SENT], m[MSG_ENTRIES])
        for r in tables["state"]:
            run.add("fixed", r[ST_T], sum(r[ST_FIXED]))
            for i, h in enumerate(r[ST_HASHED]):
                run.add(f"hash{i}", r[ST_T], h)

    def node_of(self, inc: Incident) -> int:
        return self.facts.get(inc.t0, {}).get("node", 2)

    def cut_at(self, variant: str, t: float) -> tuple[str, int] | None:
        """(kind, replica) while a replica is down or cut off by a blip."""
        inc = self.incident_at(variant, t)
        return (inc.kind, self.node_of(inc)) if inc is not None else None

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind in ("disk", "restore"):
            return self.word(inc.kind)
        if inc.kind == "blip":
            return self.word("blip" if start else "heal")
        return self.word("down" if start else "up")

    def incident_text(self, inc: Incident, start: bool) -> str:
        fact = self.facts.get(inc.t0, {})
        node = f"n{fact.get('node', 2)}"
        if inc.kind == "down":
            if start:
                return self.s("down", node=node, cause=self.cause(inc), hints=HINTS)
            return self.s("up", node=node)
        if inc.kind == "blip":
            return self.s("blip", node=node, cause=self.cause(inc)) if start else self.s("healed", node=node)
        n = fact.get("n", int(inc.severity))
        if inc.kind == "disk":
            return self.s("disk", node=node, n=n, cause=self.cause(inc))
        lo = fact.get("lo", 0)
        return self.s("restore", node=node, n=n, first=f"k{lo:05d}", last=f"k{lo + n - 1:05d}",
                      cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        out = []
        fact = self.facts.get(inc.t0, {})
        node = f"n{fact.get('node', 2)}"
        if inc.kind == "down" and fact.get("n"):
            out.append((inc.t1, self.s("warn_hints", n=fact["n"], node=node)))
        rows = run.rows("state", inc.t1 + 0.01, inc.t1 + 0.6)
        if rows and sum(rows[-1][ST_DIVERGED]):
            out.append((rows[-1][ST_T], self.s("warn_diverged", n=sum(rows[-1][ST_DIVERGED]))))
        return out

    def sent_so_far(self, run: Run, t: float) -> tuple[float | None, float, float]:
        """(entries per key repaired, entries sent, keys repaired) for the latest incident, up to t."""
        started = [i for i in run.incidents if i.t0 <= t]
        if not started:
            return None, 0.0, 0.0
        a, b = _sent_window(started[-1])
        a, b = int(a), int(min(b, t))
        sent = sum(run.series("repair", a, b + 1))
        fixed = sum(run.series("fixed", a, b + 1))
        return per_key(sent, fixed), sent, fixed

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        diverged = diverged_at(run, t)
        total = sum(diverged)

        def div_state(n: int) -> str:
            return "ok" if n == 0 else "warn" if n <= 50 else "bad"

        def div_s(s: int):
            n = sum(diverged_at(run, s + 1))
            return float(n), div_state(n)

        def stale_share(a: int, b: int) -> float | None:
            reads = sum(run.series("reads", a, b))
            return sum(run.series("stale", a, b)) / reads if reads else None

        def stale_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v <= lab.STALE_MAX else "warn" if v <= 0.01 else "bad"

        def stale_s(s: int):
            v = stale_share(s, s + 1)
            return (v or 0.0), stale_state(v)

        def sent_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v <= lab.SENT_MAX else "bad"

        def sent_s(s: int):
            v = self.sent_so_far(run, s + 1)[0]
            return (0.0 if v is None else min(v, 10 * lab.SENT_MAX)), sent_state(v)

        stale = stale_share(int(t) - 10, int(t))
        per, sent, fixed = self.sent_so_far(run, t)
        per_text = "–" if per is None else self.s("per_key", v=per) if per != math.inf else "∞"
        tiles = [
            Tile(self.s("tile_diverged"), fmt_int(total), "=0", div_state(total), history(run, t, div_s)),
            Tile(self.s("tile_stale"), "–" if stale is None else f"{stale:.1%}", f"≤{lab.STALE_MAX:.1%}",
                 stale_state(stale), history(run, t, stale_s)),
            Tile(self.s("tile_sent"), per_text, f"≤{lab.SENT_MAX:.0f}", sent_state(per), history(run, t, sent_s)),
        ]
        s = int(t)
        work = [sum(run.series(f"hash{i}", s - 1, s)) for i in range(lab.REPLICAS)]
        bars = [Bar(f"n{i}", [(w, EXTRA2 if w > lab.HASH_MAX else BLUE)]) for i, w in enumerate(work)]
        cut = self.cut_at(variant, t)
        repairing = sum(run.series("fixed", s - 1, s))
        if cut is not None and cut[0] == "down":
            headline, colour = self.s("head_down", node=f"n{cut[1]}"), RED
        elif cut is not None:
            headline, colour = self.s("head_blip", node=f"n{cut[1]}"), ORANGE
        elif total:
            worst = max(range(lab.REPLICAS), key=lambda i: diverged[i])
            headline, colour = self.s("head_diverged", n=total, node=f"n{worst}"), ORANGE
        elif repairing:
            headline, colour = self.s("head_repaired", n=repairing), BLUE
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, lab.HASH_MAX, self.s("limit"), headline, colour, title=self.s("hash_title"),
                       subtitle=self.s("hash_sub"), top=max(lab.HASH_MAX * 1.5, max(work) * 1.05))

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        stale = run.total("stale", t)
        total = sum(diverged_at(run, t))
        return [
            (self.s("stat_reads"), fmt_int(run.total("reads", t)), WHITE),
            (self.s("stat_writes"), fmt_int(run.total("writes", t)), WHITE),
            (self.s("stat_stale"), fmt_int(stale), RED if stale else MUTED),
            (self.s("stat_diverged"), fmt_int(total), EXTRA2 if total else MUTED),
            (self.s("stat_repair"), fmt_int(run.total("repair", t)), MUTED),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("replication", [])), (EXTRA2, run.hist.get("repair", []))]

    def chart_limit(self):
        return None

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = MerkleWorld
