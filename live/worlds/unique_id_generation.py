"""World for lab unique_id_generation (Fly.io Gossip Glomers #1 and #2). Its words are in
labs/unique_id_generation/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.unique_id_generation import lab
from labs.unique_id_generation.scenario import ECHO, GENERATE
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, history


_s = strings("unique_id_generation")  # one of the lab's STRINGS, for the goal measures below


OP_START, OP_KIND, OP_NODE, OP_END, OP_OK, OP_ID, OP_DUP, OP_COMPACT = range(8)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED = range(4)


def _gen(run: Run, a: float, b: float, upto: float = float("inf")) -> list[tuple]:
    """generate requests started in [a, b) and finished by upto."""
    return [o for o in run.rows("ops", a, min(b, upto)) if o[OP_KIND] == GENERATE and o[OP_END] <= upto]


def ordered_share(ops: list[tuple], gap: float, per_node: bool) -> float | None:
    """Share of ids larger than every id handed out at least `gap` seconds earlier
    (by the same node if per_node). Ids that are not 64-bit ints count as not ordered."""
    got = sorted((o for o in ops if o[OP_OK]), key=lambda o: o[OP_END])
    if not got:
        return None
    good = total = 0
    best: dict[int, int] = {}
    j = 0
    for o in got:
        while j < len(got) and got[j][OP_END] <= o[OP_END] - gap:
            prev = got[j]
            key = prev[OP_NODE] if per_node else 0
            if prev[OP_ID] is not None:
                best[key] = max(best.get(key, -1), prev[OP_ID])
            j += 1
        key = o[OP_NODE] if per_node else 0
        if j == 0 or (per_node and key not in best):
            continue
        total += 1
        good += o[OP_ID] is not None and o[OP_ID] > best.get(key, -1)
    return good / total if total else None


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t0


def _echo(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    rows = [o for o in run.rows("ops", a, min(b, upto)) if o[OP_KIND] == ECHO]
    if not rows:
        return None, "–"
    v = sum(o[OP_OK] for o in rows) / len(rows)
    return v, f"{v:.0%}"


def _unique(run: Run, inc: Incident, upto: float):
    rows = _gen(run, inc.t0 - lab.BEFORE, inc.t1, upto)
    if not any(o[OP_OK] for o in rows):
        return None, _s("none")
    dups = sum(o[OP_DUP] for o in rows)
    return dups, _s("dups", n=dups)


def _available(run: Run, inc: Incident, upto: float):
    rows = _gen(run, inc.t0, inc.t1, upto)
    if not rows:
        return None, "–"
    v = sum(o[OP_OK] for o in rows) / len(rows)
    return v, f"{v:.0%}"


def _compact(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    rows = [o for o in _gen(run, a, b, upto) if o[OP_OK]]
    if not rows:
        return None, "–"
    v = sum(o[OP_COMPACT] for o in rows) / len(rows)
    return v, f"{v:.0%}"


def _ordered(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = ordered_share(_gen(run, a, b, upto), lab.ORDER_GAP, per_node=False)
    return v, "–" if v is None else f"{v:.0%}"


def _monotonic(run: Run, inc: Incident, upto: float):
    """How many ids were smaller than an id the same node handed out before (it went backwards)."""
    rows = _gen(run, inc.t0 - 2, inc.t1, upto)
    v = ordered_share(rows, lab.REPLY_JITTER, per_node=True)
    if v is None:
        return None, "–"
    judged = sum(1 for o in rows if o[OP_OK])
    back = round((1 - v) * judged)
    return back, _s("back", n=back)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _calm_and_during(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t1


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _echo, lambda v: v is not None and v >= lab.ECHO_MIN, key="echo"),
    GoalSpec("", "during", "", _calm_and_during, _unique, lambda v: v == 0, settle_extra=2.0, key="unique"),
    GoalSpec("", "during", "", _during, _available, lambda v: v is not None and v >= lab.AVAILABLE_MIN,
             settle_extra=2.0, key="available"),
    GoalSpec("", "before", "", _before, _compact, lambda v: v is not None and v >= lab.COMPACT_MIN,
             key="compact"),
    GoalSpec("", "before", "", _before, _ordered, lambda v: v is not None and v >= lab.ORDERED_MIN,
             key="ordered"),
    GoalSpec("", "during", "", _during, _monotonic, lambda v: v == 0, settle_extra=2.0, key="monotonic"),
]


# The event verbs (text.VERBS keys) for each kind of incident: (starting, ending).
VERB_KEYS = {"split": ("split", "heal"), "clock": ("clock", "sync"), "migrate": ("move", "back")}


class UniqueIdsWorld(World):
    id = "unique_id_generation"
    view = "cluster"
    stage_colours = (RED, EXTRA2, EXTRA1, BLUE)
    legend = [(BLUE, "node", "◉"), (EXTRA2, "clock_back", "◉"), (RED, "duplicate", "◉"),
              (WHITE, "request"), (GREEN, "reply"), (RED, "partition", "┆")]
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
    }
    goals = GOALS

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            if o[OP_KIND] == GENERATE:
                name = "gen_failed" if not o[OP_OK] else "dup" if o[OP_DUP] else "unique"
                run.add(name, o[OP_END])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
        for m in tables["msgs"]:
            run.add("msgs", m[MSG_SENT])
        run.data.setdefault("groups", {}).update(piece.get("groups", {}))
        run.data.setdefault("victims", {}).update(piece.get("victims", {}))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(VERB_KEYS[inc.kind][0 if start else 1])

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"end_{inc.kind}")
        return self.s(f"start_{inc.kind}", seconds=inc.severity, cause=self.cause(inc))

    def active(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def groups_at(self, variant: str, t: float) -> list[int] | None:
        inc = self.active(variant, t)
        groups = self.runs[variant].data.get("groups", {}).get(inc.t0) if inc else None
        if not groups:
            return None
        out = [0] * lab.NODES
        for g, members in enumerate(groups):
            for i in members:
                out[i] = g
        return out

    def skewed_at(self, variant: str, t: float) -> tuple[int, float] | None:
        """(node, seconds behind) while a node's clock is stepped back."""
        inc = self.active(variant, t)
        if inc is None or inc.kind == "split":
            return None
        return self.runs[variant].data["victims"][inc.t0], inc.severity

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        dups = sum(o[OP_DUP] for o in _gen(run, t - 30, t, t))

        def dups_s(s: int):
            v = run.series("dup", s, s + 1)[0]
            return v, "bad" if v else "ok"

        recent = _gen(run, t - 5, t - 1, t)
        answered = sum(o[OP_OK] for o in recent) / len(recent) if recent else None

        def ans_state(v):
            return "idle" if v is None else "bad" if v < lab.AVAILABLE_MIN else "ok"

        def ans_s(s: int):
            ok = run.series("unique", s, s + 1)[0] + run.series("dup", s, s + 1)[0]
            bad = run.series("gen_failed", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else None
            return (v or 0.0), ans_state(v)

        ordered = ordered_share(_gen(run, t - 10, t, t), lab.ORDER_GAP, per_node=False)

        def ord_state(v):
            return "idle" if v is None else "bad" if v < lab.ORDERED_MIN else "ok"

        def ord_s(s: int):
            v = ordered_share(_gen(run, s - 5, s + 1, s + 1), lab.ORDER_GAP, per_node=False)
            return (v or 0.0), ord_state(v)

        tiles = [
            Tile(self.s("tile_dups"), str(dups), "=0", "bad" if dups else "ok", history(run, t, dups_s)),
            Tile(self.s("tile_answers"), "–" if answered is None else f"{answered:.0%}", "≥99%",
                 ans_state(answered), history(run, t, ans_s)),
            Tile(self.s("tile_ordered"), "–" if ordered is None else f"{ordered:.0%}", "≥99%",
                 ord_state(ordered), history(run, t, ord_s)),
        ]
        last = _gen(run, t - 1, t, t)
        asked = len([o for o in run.rows("ops", t - 1, t)])
        bars = [Bar(self.s("bar_clients"), [(float(asked), WHITE)]),
                Bar(self.s("bar_ids"), [(float(sum(o[OP_OK] and not o[OP_DUP] for o in last)), GREEN),
                                        (float(sum(o[OP_DUP] for o in last)), RED)])]
        inc = self.active(variant, t)
        skew = self.skewed_at(variant, t)
        if dups:
            headline, colour = self.s("head_dups", n=dups), RED
        elif inc is not None and skew is not None:
            headline, colour = self.s("head_skew", node=skew[0], seconds=skew[1]), EXTRA2
        elif inc is not None:
            headline, colour = self.s("head_split"), RED
        else:
            headline, colour = self.s("head_ok", n=len(last)), MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("requests"),
                       top=max(1.0, asked * 1.4))

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        stats = self.request_stats(run, "ops", OP_START, OP_END, OP_OK, t)
        s = int(t)
        partial = [o for o in run.rows("ops", s - run.max_dur.get("ops", 0.0) - 1, t) if s <= o[OP_END] < t]
        dups = run.total("dup", t) + sum(1 for o in partial if o[OP_DUP])
        stats[2] = (self.s("stat_dups"), fmt_int(dups), RED if dups else MUTED)  # dups instead of waiting
        return stats

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("unique", [])), (RED, run.hist.get("dup", [])),
                (EXTRA2, run.hist.get("gen_failed", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = UniqueIdsWorld
