"""World for lab consistent_hashing. Its words are in labs/consistent_hashing/text/<lang>.py."""

from __future__ import annotations

from dataclasses import replace

from core.i18n import strings
from labs.consistent_hashing import lab
from labs.consistent_hashing.scenario import SLOTS
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, LIMIT, MUTED, RED, WHITE
from live.worlds.base import Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history

R_START, R_SLOT, R_HIT, R_END, R_OK = range(5)
C_T, C_OP, C_SLOT, C_MOVED, C_IDEAL, C_IMBALANCE, C_COUNTS, C_LIVE = range(8)
# The words for an incident starting and ending, by kind: VERBS keys and STRINGS keys.
VERBS = {"crash": ("lost", "back"), "scale": ("join", "leave"), "deploy": ("stop", "start")}
TEXTS = {"crash": ("lost", "replaced"), "scale": ("join", "leave"), "deploy": ("stop", "start")}

_s = strings("consistent_hashing")  # one of the lab's STRINGS, for the goal measures below


def _changes(run: Run) -> list[tuple]:
    return run.data.setdefault("changes", [])


def _change_at(run: Run, t: float) -> tuple | None:
    """The cluster change made at t (an incident starting or ending)."""
    return next((c for c in _changes(run) if abs(c[C_T] - t) < 1e-6 and c[C_OP] != "start"), None)


def _layout_at(run: Run, t: float) -> tuple | None:
    """The latest change at or before t: who is in the cluster and how many keys each owns."""
    last = None
    for c in _changes(run):
        if c[C_T] > t:
            break
        last = c
    return last


def _hit_ratio(run: Run, a: float, b: float) -> float | None:
    rows = run.rows("reads", a, b)
    return sum(1 for r in rows if r[R_HIT]) / len(rows) if rows else None


def _calm(run: Run, inc: Incident) -> tuple[float, float] | None:
    """Hit ratio and database reads/s in the calm before a change (kept once known)."""
    calm = run.data.setdefault("calm", {})
    if inc.t0 not in calm:
        a, b = inc.t0 - lab.BEFORE, inc.t0
        rows = run.rows("reads", a, b)
        if not rows or run.end < b:
            return None
        misses = sum(1 for r in rows if not r[R_HIT])
        calm[inc.t0] = ((len(rows) - misses) / len(rows), max(1.0, misses / lab.BEFORE))
    return calm[inc.t0]


# ---------------------------------------------------------------- goals


def _balance(run: Run, inc: Incident, upto: float):
    c = _layout_at(run, min(upto, inc.t0 - 1e-6))
    if c is None:
        return None, "–"
    return c[C_IMBALANCE], f"{c[C_IMBALANCE]:.2f}x"


def _moved(run: Run, inc: Incident, upto: float):
    c = _change_at(run, inc.t0)
    if c is None or c[C_T] > upto:
        return None, "–"
    v = c[C_MOVED] / c[C_IDEAL]
    return v, _s("per_n", value=v)


def _hits(run: Run, inc: Incident, upto: float):
    calm = _calm(run, inc)
    b = min(inc.t0 + lab.AFTER, upto)
    now = _hit_ratio(run, inc.t0, b) if b > inc.t0 else None
    if calm is None or now is None:
        return None, "–"
    v = now / calm[0] if calm[0] else 1.0
    return v, f"{v:.0%}"


def _db(run: Run, inc: Incident, upto: float):
    calm = _calm(run, inc)
    b = min(inc.t0 + lab.AFTER, upto)
    if calm is None or b <= inc.t0:
        return None, "–"
    misses = sum(1 for r in run.rows("reads", inc.t0, b) if not r[R_HIT])
    v = misses / max(1.0, b - inc.t0) / calm[1]
    return v, f"{v:.1f}x"


# The rule and fix of each goal are text.GOALS[key]; the order is lab.stage_of's.
GOALS = [
    GoalSpec("", "before", "", lambda i: (i.t0 - lab.BEFORE, i.t0), _balance,
             lambda v: v is not None and v <= lab.BALANCE_MAX, key="balance"),
    GoalSpec("", "during", "", lambda i: (i.t0, i.t0 + 0.5), _moved,
             lambda v: v is not None and v <= lab.MOVED_MAX, key="moved"),
    GoalSpec("", "after", "", lambda i: (i.t0, i.t0 + lab.AFTER), _hits,
             lambda v: v is not None and v >= lab.HIT_KEEP, settle_extra=1.5, key="hits"),
    GoalSpec("", "after", "", lambda i: (i.t0, i.t0 + lab.AFTER), _db,
             lambda v: v is not None and v <= lab.DB_PEAK, settle_extra=1.5, key="db"),
]


def _share(x: float) -> tuple[int, int, int]:
    """A node's colour from its keys vs the average node."""
    return BLUE if x <= 1.2 else EXTRA1 if x <= lab.BALANCE_MAX else EXTRA2


class ConsistentHashingWorld(World):
    id = "consistent_hashing"
    view = "fanin"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "fair", "◉"), (EXTRA1, "busy", "◉"), (EXTRA2, "hot", "◉"), (DIM, "out", "◉"),
              (WHITE, "read"), (RED, "miss"), (LIMIT, "limit", "┄")]
    tables = {
        "reads": Table(sort=R_START, times=(R_START, R_END)),
        "changes": Table(sort=C_T, times=(C_T,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 500.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["reads"]:
            run.add("reads", r[R_START])
            run.add("hits" if r[R_HIT] else "misses" if r[R_OK] else "refused", r[R_START])
            run.add("served" if r[R_OK] else "failed", r[R_END])
        _changes(run).extend(tables["changes"])
        # Name the node in the incident's events (the incident itself only knows its kind).
        for c in tables["changes"]:
            if c[C_OP] == "start":
                continue
            for k, e in enumerate(run.timeline):
                if e.kind in ("start", "end") and abs(e.t - c[C_T]) < 1e-6:
                    inc = run.incidents[e.incident]
                    run.timeline[k] = replace(e, text=self._incident_text(inc, e.kind == "start", SLOTS[c[C_SLOT]]))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(VERBS.get(inc.kind, VERBS["crash"])[0 if start else 1])

    def _incident_text(self, inc: Incident, start: bool, node: str | None) -> str:
        key = TEXTS.get(inc.kind, TEXTS["crash"])[0 if start else 1]
        return self.s(key if node else f"{key}_plain", node=node, cause=self.cause(inc))

    def incident_text(self, inc: Incident, start: bool) -> str:
        return self._incident_text(inc, start, None)

    # ---------------------------------------------------------------- what the pictures share

    def layout(self, variant: str, t: float) -> tuple | None:
        run = self.runs.get(variant)
        return _layout_at(run, t) if run else None

    def node_colours(self, variant: str, t: float) -> list[tuple[int, int, int]]:
        c = self.layout(variant, t)
        if c is None:
            return [DIM] * len(SLOTS)
        live = [n for n, on in zip(c[C_COUNTS], c[C_LIVE]) if on]
        avg = sum(live) / len(live)
        return [_share(n / avg) if on else DIM for n, on in zip(c[C_COUNTS], c[C_LIVE])]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        s = int(t)
        hits, misses, refused = (run.series(n, s - 1, s)[0] for n in ("hits", "misses", "refused"))
        reads = hits + misses + refused
        ratio = hits / reads if reads else None
        calm = sum(run.series("hits", s - 30, s)) / max(1.0, sum(run.series("reads", s - 30, s)))

        def hits_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v >= calm * lab.HIT_KEEP else "warn" if v >= calm * 0.75 else "bad"

        def hits_s(k: int):
            h, n = run.series("hits", k, k + 1)[0], run.series("reads", k, k + 1)[0]
            v = h / n if n else None
            return (v or 0.0), hits_state(v)

        def db_state(v: float) -> str:
            return "bad" if v >= lab.DB_CAPACITY else "warn" if v >= lab.DB_CAPACITY * 0.6 else "ok"

        def db_s(k: int):
            v = run.series("misses", k, k + 1)[0] + run.series("refused", k, k + 1)[0]
            return v, db_state(v)

        def spread_at(x: float) -> float | None:
            c = _layout_at(run, x)
            return None if c is None else c[C_IMBALANCE]

        def spread_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v <= lab.BALANCE_MAX else "warn" if v <= 2.0 else "bad"

        def spread_s(k: int):
            v = spread_at(k + 1)
            return (v or 0.0), spread_state(v)

        db = misses + refused
        spread = spread_at(t)
        tiles = [
            Tile(self.s("tile_hits"), "–" if ratio is None else f"{ratio:.0%}", f"≥{calm * lab.HIT_KEEP:.0%}",
                 hits_state(ratio), history(run, t, hits_s)),
            Tile(self.s("tile_db"), f"{db:.0f}", f"<{lab.DB_CAPACITY:.0f}", db_state(db), history(run, t, db_s)),
            Tile(self.s("tile_spread"), "–" if spread is None else f"{spread:.2f}x", f"≤{lab.BALANCE_MAX}x",
                 spread_state(spread), history(run, t, spread_s)),
        ]
        bars = [Bar(self.s("bar_cache"), [(hits, BLUE)]),
                Bar(self.s("bar_db"), [(misses, EXTRA2), (refused, RED)])]
        recent = [c for c in _changes(run) if c[C_OP] != "start" and t - 8 <= c[C_T] <= t]
        layout = _layout_at(run, t)
        if recent:
            c = recent[-1]
            bad = c[C_MOVED] > lab.MOVED_MAX * c[C_IDEAL]
            headline = self.s("head_change", node=SLOTS[c[C_SLOT]], moved=c[C_MOVED], hits=ratio or 0.0)
            colour = RED if bad else MUTED
        elif layout is not None and spread is not None and spread > lab.BALANCE_MAX:
            busiest = max(range(len(SLOTS)), key=lambda i: layout[C_COUNTS][i])
            headline, colour = self.s("head_hot", node=SLOTS[busiest], spread=spread), EXTRA2
        else:
            headline, colour = self.s("head_ok", hits=ratio or 0.0, db=db), MUTED
        return Traffic(tiles, bars, lab.DB_CAPACITY, self.s("limit", limit=lab.DB_CAPACITY), headline, colour,
                       title=self.s("reads"), top=max(self.rate * 1.1, reads * 1.05))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "reads", R_START, R_END, R_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA2, run.hist.get("misses", [])), (RED, run.hist.get("refused", []))]

    def chart_limit(self):
        return lab.DB_CAPACITY, self.s("chart_limit", limit=lab.DB_CAPACITY)

    def legend_notes(self) -> list[str]:
        return [self.s("note_nodes"), self.s("note_chart")]


WORLD = ConsistentHashingWorld
