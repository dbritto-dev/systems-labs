"""World for lab unique_ids (Fly.io Gossip Glomers #1 and #2)."""

from __future__ import annotations

from labs.unique_ids import lab
from labs.unique_ids.scenario import ECHO, GENERATE
from live.canvas import BLUE, EXTRA2, GREEN, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Stage, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

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
        return None, "none"
    dups = sum(o[OP_DUP] for o in rows)
    return dups, f"{dups} dups"


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
    return back, f"{back} back"


GOALS = [
    GoalSpec("Echo works", "before", "reply echo_ok", _before, _echo,
             lambda v: v is not None and v >= lab.ECHO_MIN),
    GoalSpec("Unique", "during", "add the node to the id",
             lambda i: (i.t0 - lab.BEFORE, i.t1), _unique, lambda v: v == 0, settle_extra=2.0),
    GoalSpec("Available ≥ 99%", "during", "don't ask other nodes",
             lambda i: (i.t0, i.t1), _available, lambda v: v is not None and v >= lab.AVAILABLE_MIN,
             settle_extra=2.0),
    GoalSpec("64-bit ints", "before", "pack the id in an int", _before, _compact,
             lambda v: v is not None and v >= lab.COMPACT_MIN),
    GoalSpec("Time-ordered", "before", "put milliseconds first", _before, _ordered,
             lambda v: v is not None and v >= lab.ORDERED_MIN),
    GoalSpec("Never backwards", "during", "keep the last timestamp",
             lambda i: (i.t0, i.t1), _monotonic, lambda v: v == 0, settle_extra=2.0),
]


class UniqueIdsWorld(World):
    id = "unique_ids"
    title = "Unique IDs (Gossip Glomers #1-2)"
    files = ("labs/unique_ids/main.py",)
    view = "cluster"
    stages = [Stage(label, story, colour, nxt) for (label, story, nxt), colour
              in zip(lab.STAGES, (RED, EXTRA2, (250, 190, 135), BLUE))]
    legend = [(BLUE, "node", "◉"), (EXTRA2, "clock stepped back", "◉"), (RED, "gave a duplicate", "◉"),
              (WHITE, "request"), (GREEN, "reply"), (RED, "partition", "┆")]
    incident_name = "Incident"
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
                name = "failed" if not o[OP_OK] else "dup" if o[OP_DUP] else "unique"
                run.add(name, o[OP_END])
            run.add("served" if o[OP_OK] else "bad", o[OP_END])
        for m in tables["msgs"]:
            run.add("msgs", m[MSG_SENT])
        run.data.setdefault("groups", {}).update(piece.get("groups", {}))
        run.data.setdefault("victims", {}).update(piece.get("victims", {}))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return {"split": ("SPLIT", "HEAL"), "clock": ("CLOCK", "SYNC"), "migrate": ("MOVE", "BACK")}[
            inc.kind][0 if start else 1]

    def incident_title(self, inc: Incident) -> str:
        name = {"split": "Partition", "clock": "Clock jump", "migrate": "Migration"}[inc.kind]
        return f"{name} #{inc.index + 1}"

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return {"split": "the network is whole again", "clock": "the clock is right again",
                    "migrate": "the node is back, its clock right"}[inc.kind]
        what = {"split": "the nodes are split in two",
                "clock": f"a clock jumped back {inc.severity:.1f} s",
                "migrate": f"a node is cut off, clock back {inc.severity:.1f} s"}[inc.kind]
        return f"{what}: {inc.cause}"

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
            bad = run.series("failed", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else None
            return (v or 0.0), ans_state(v)

        ordered = ordered_share(_gen(run, t - 10, t, t), lab.ORDER_GAP, per_node=False)

        def ord_state(v):
            return "idle" if v is None else "bad" if v < lab.ORDERED_MIN else "ok"

        def ord_s(s: int):
            v = ordered_share(_gen(run, s - 5, s + 1, s + 1), lab.ORDER_GAP, per_node=False)
            return (v or 0.0), ord_state(v)

        tiles = [
            Tile("Dups", str(dups), "=0", "bad" if dups else "ok", history(run, t, dups_s)),
            Tile("Answers", "–" if answered is None else f"{answered:.0%}", "≥99%", ans_state(answered),
                 history(run, t, ans_s)),
            Tile("Ordered", "–" if ordered is None else f"{ordered:.0%}", "≥99%", ord_state(ordered),
                 history(run, t, ord_s)),
        ]
        last = _gen(run, t - 1, t, t)
        asked = len([o for o in run.rows("ops", t - 1, t)])
        bars = [Bar("Clients", [(float(asked), WHITE)]),
                Bar("Ids", [(float(sum(o[OP_OK] and not o[OP_DUP] for o in last)), GREEN),
                            (float(sum(o[OP_DUP] for o in last)), RED)])]
        inc = self.active(variant, t)
        skew = self.skewed_at(variant, t)
        if dups:
            headline, colour = f"{dups} duplicate ids in the last 30 s", RED
        elif inc is not None and skew is not None:
            headline, colour = f"n{skew[0]}'s clock is {skew[1]:.1f} s behind", EXTRA2
        elif inc is not None:
            headline, colour = "The nodes cannot talk: ids must not need to", RED
        else:
            headline, colour = f"Every id unique ({len(last)} ids/s)", MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title="Requests",
                       top=max(1.0, asked * 1.4))

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("ops", 0.0)
        partial = [o for o in run.rows("ops", s - span - 1, t) if s <= o[OP_END] < t]
        served = run.total("served", t) + sum(1 for o in partial if o[OP_OK])
        failed = run.total("bad", t) + sum(1 for o in partial if not o[OP_OK])
        dups = run.total("dup", t) + sum(1 for o in partial if o[OP_DUP])
        recent = [o[OP_END] - o[OP_START] for o in run.rows("ops", t - 5 - span, t) if t - 5 <= o[OP_END] < t]
        return [
            ("served", fmt_int(served), GREEN),
            ("failed", fmt_int(failed), RED if failed else MUTED),
            ("dups", fmt_int(dups), RED if dups else MUTED),
            ("p50", fmt_ms(percentile(recent, 50)), WHITE),
            ("p99", fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("unique", [])), (RED, run.hist.get("dup", [])),
                (EXTRA2, run.hist.get("failed", []))]

    def legend_notes(self) -> list[str]:
        return ["Chart: ids per second: unique, duplicate, failed."]


WORLD = UniqueIdsWorld
