"""World for lab grow_only_counter (Fly.io Gossip Glomers #4). Its words are in labs/grow_only_counter/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.grow_only_counter import lab
from labs.grow_only_counter.scenario import ADD, CLIENT_TIMEOUT, KV_REQ, READ
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, MUTED, PURPLE, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history

_s = strings("grow_only_counter")  # one of the lab's STRINGS, for the goal measures below


OP_START, OP_KIND, OP_NODE, OP_VALUE, OP_END, OP_OK, OP_LOW, OP_HIGH = range(8)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_KIND = range(5)
CAS_T, CAS_NODE, CAS_OK = range(3)


def right(r: tuple) -> bool:
    """A read whose value is inside its band: every add acknowledged a while before, nothing extra."""
    return bool(r[OP_OK]) and r[OP_LOW] <= r[OP_VALUE] <= r[OP_HIGH]


def _reads(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    span = run.max_dur.get("ops", 0.0)
    return [r for r in run.rows("ops", a, min(b, upto)) if r[OP_KIND] == READ and r[OP_OK]
            and r[OP_END] <= upto and r[OP_START] >= a - span * 0]


def _share_right(reads: list[tuple]):
    if not reads:
        return None, "–"
    v = sum(right(r) for r in reads) / len(reads)
    return v, f"{v:.0%}"


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE[0], inc.t0 - lab.BEFORE[1]


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.AFTER[0], inc.t1 + lab.AFTER[1]


def _stored(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    n = sum(1 for m in run.rows("msgs", a, min(b, upto)) if m[MSG_KIND] == KV_REQ)
    return float(n), _s("ops", n=n)


def _right_before(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    return _share_right(_reads(run, a, b, upto))


def _conflicts(run: Run, inc: Incident, upto: float):
    rows = run.rows("cas", inc.t0, min(inc.t1, upto))
    if not rows:
        return (0.0, "0%") if upto > inc.t0 else (None, "–")
    v = sum(1 for c in rows if not c[CAS_OK]) / len(rows)
    return v, f"{v:.0%}"


def _answered(run: Run, inc: Incident, upto: float):
    adds = [r for r in run.rows("ops", inc.t0, min(inc.t1, upto)) if r[OP_KIND] == ADD and r[OP_END] <= upto]
    if not adds:
        return None, "–"
    v = sum(1 for r in adds if r[OP_OK]) / len(adds)
    return v, f"{v:.0%}"


def _right_after(run: Run, inc: Incident, upto: float):
    a, b = _after(inc)
    return _share_right(_reads(run, a, b, upto))


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _stored, lambda v: v is not None and v > 0,
             settle_extra=lab.BEFORE[1], key="stored"),
    GoalSpec("", "before", "", _before, _right_before, lambda v: v is not None and v >= lab.RIGHT_MIN,
             settle_extra=lab.BEFORE[1], key="right"),
    GoalSpec("", "during", "", _during, _conflicts, lambda v: v is not None and v < lab.CONFLICTS_MAX,
             key="conflicts"),
    GoalSpec("", "during", "", _during, _answered, lambda v: v is not None and v >= lab.ANSWERED_MIN,
             settle_extra=CLIENT_TIMEOUT + 0.5, key="answered"),
    GoalSpec("", "after", "", _after, _right_after, lambda v: v is not None and v >= lab.RIGHT_MIN,
             settle_extra=1.5, key="after"),
]


class GCounterWorld(World):
    id = "grow_only_counter"
    view = "fanin"
    stage_colours = (RED, EXTRA3, EXTRA2, BLUE)
    legend = [(BLUE, "node", "◉"), ([EXTRA2, RED], "reads_off", "◉"), (PURPLE, "seq_kv", "◉"),
              (WHITE, "client_request"), (BLUE, "kv_request"), (GREEN, "kv_ok"), (RED, "cas_conflict")]
    incident_verbs = ("burst", "calm")
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "cas": Table(sort=CAS_T, times=(CAS_T,)),
    }
    goals = GOALS

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["ops"]:
            if o[OP_KIND] == ADD:
                run.add("adds", o[OP_START])
                run.add("adds_ok" if o[OP_OK] else "adds_failed", o[OP_START])
            elif o[OP_OK]:
                run.add("reads", o[OP_START])
                run.add("reads_right" if right(o) else "reads_wrong", o[OP_START])
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
        for m in tables["msgs"]:
            if m[MSG_KIND] == KV_REQ:
                run.add("kv", m[MSG_SENT])
        for c in tables["cas"]:
            run.add("cas", c[CAS_T])
            if not c[CAS_OK]:
                run.add("conflicts", c[CAS_T])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_title(self, inc: Incident) -> str:
        name = self.s("title_burst" if inc.kind == "burst" else "title_slow")
        return self.screen.INCIDENT_TITLE.format(name=name, n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if inc.kind == "slow":
            return self.word("slow" if start else "fast")
        return self.word("burst" if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s("back_to_normal")
        key = "slow_text" if inc.kind == "slow" else "burst_text"
        return self.s(key, factor=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1)):
            cas, bad = run.series("cas", s, s + 1)[0], run.series("conflicts", s, s + 1)[0]
            if cas >= 5 and bad / cas >= 0.5:
                return [(s + 1.0, self.s("warn_conflicts", share=bad / cas))]
        return []

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def node_off(self, run: Run, t: float) -> list[int]:
        """Per node: reads in the last 2 s that were off (lost adds, or counted twice)."""
        off = [0] * lab.NODES
        for r in run.rows("ops", t - 2.0, t + 1e-9):
            if r[OP_KIND] == READ and r[OP_OK] and r[OP_END] <= t and not right(r):
                off[r[OP_NODE]] += 1
        return off

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        reads = [r for r in run.rows("ops", t - 5, t) if r[OP_KIND] == READ and r[OP_OK] and r[OP_END] <= t]
        share = sum(right(r) for r in reads) / len(reads) if reads else None

        def right_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.RIGHT_MIN else "ok"

        def right_s(s: int):
            ok, bad = run.series("reads_right", s, s + 1)[0], run.series("reads_wrong", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else None
            return (v or 0.0), right_state(v)

        cas = run.rows("cas", t - 5, t)
        conf = sum(1 for c in cas if not c[CAS_OK]) / len(cas) if cas else 0.0

        def conf_state(v: float) -> str:
            return "bad" if v >= lab.CONFLICTS_MAX else "ok"

        def conf_s(s: int):
            n, bad = run.series("cas", s, s + 1)[0], run.series("conflicts", s, s + 1)[0]
            v = bad / n if n else 0.0
            return v, conf_state(v)

        adds = [r for r in run.rows("ops", t - 5 - CLIENT_TIMEOUT, t - CLIENT_TIMEOUT) if r[OP_KIND] == ADD]
        answered = sum(1 for r in adds if r[OP_OK]) / len(adds) if adds else None

        def ans_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.ANSWERED_MIN else "ok"

        def ans_s(s: int):
            ok, bad = run.series("adds_ok", s, s + 1)[0], run.series("adds_failed", s, s + 1)[0]
            v = ok / (ok + bad) if ok + bad else None
            return (v or 0.0), ans_state(v)

        tiles = [
            Tile(self.s("tile_right"), "–" if share is None else f"{share:.0%}", "≥99%", right_state(share),
                 history(run, t, right_s)),
            Tile(self.s("tile_adds"), "–" if answered is None else f"{answered:.0%}", "≥99%",
                 ans_state(answered), history(run, t, ans_s)),
            Tile(self.s("tile_conflict"), f"{conf:.0%}", "<10%", conf_state(conf), history(run, t, conf_s)),
        ]
        ops = run.count("ops", t - 1, t)
        kv = [m for m in run.rows("msgs", t - 1, t) if m[MSG_KIND] == KV_REQ]
        conflicts = sum(1 for c in run.rows("cas", t - 1, t) if not c[CAS_OK])
        bars = [Bar(self.s("bar_clients"), [(float(ops), WHITE)]),
                Bar(self.s("bar_kv"), [(float(max(0, len(kv) - conflicts)), BLUE), (float(conflicts), RED)])]
        inc = self.incident_at(variant, t)
        last = next((r for r in reversed(run.rows("ops", t - 3, t)) if r[OP_KIND] == READ and r[OP_OK]
                     and r[OP_END] <= t), None)
        if inc is not None and conf >= lab.CONFLICTS_MAX:
            headline, colour = self.s("head_conflicts", share=conf), RED
        elif share is not None and share < lab.RIGHT_MIN:
            lost = (last[OP_LOW] - last[OP_VALUE]) if last and last[OP_VALUE] < last[OP_LOW] else 0
            headline = self.s("head_missing", lost=lost) if lost else self.s("head_off")
            colour = RED
        elif last is not None:
            headline, colour = self.s("head_total", total=last[OP_VALUE]), MUTED
        else:
            headline, colour = self.s("head_waiting"), MUTED
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("requests"),
                       top=max(1.0, (len(kv) + ops) * 1.1))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        kv, bad = run.hist.get("kv", []), run.hist.get("conflicts", [])
        ok = [max(0.0, k - (bad[i] if i < len(bad) else 0.0)) for i, k in enumerate(kv)]
        return [(BLUE, ok), (RED, bad)]

    def chart_limit(self):
        return None

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = GCounterWorld
