"""World for lab geo_replication. Its words are in labs/geo_replication/text/<lang>.py."""

from __future__ import annotations

import math

from labs.geo_replication import lab, scenario
from labs.geo_replication.api import CAPACITY, FAILOVER, REGIONS
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, LIMIT, MUTED, PURPLE, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, fmt_ms, history, percentile,
)

OP_START, OP_HOME, OP_KIND, OP_OWN, OP_FIRST, OP_SERVED, OP_END, OP_OK, OP_STALE, OP_TRIES = range(10)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_USER = range(5)
REG_T, REG_UP, REG_CUT, REG_DNS, REG_BEHIND, REG_BUSY, REG_OWN, REG_OTHER, REG_SHED, REG_RISK = range(10)
READ, WRITE = scenario.READ, scenario.WRITE
BOUND = {READ: lab.READ_P99_MAX, WRITE: lab.WRITE_P99_MAX}
VERBS = {"down": ("down", "up"), "partition": ("cut", "joined"), "slow": ("slow", "normal"), "peak": ("peak", "calm")}


def slow(o: tuple) -> bool:
    """An answer slower than its kind's p99 bound: it crossed an ocean, or waited for a retry."""
    return o[OP_END] - o[OP_START] > BOUND[o[OP_KIND]]


def behind_colour(keys: int):
    """A region's colour from how many acknowledged writes it still lacks."""
    return BLUE if keys <= 2 else EXTRA1 if keys < 20 else EXTRA2 if keys < 100 else EXTRA3


def hit_of(run: Run, inc: Incident) -> int:
    return run.data.get("hits", {}).get(inc.t0, 0)


def cut_of(run: Run, inc: Incident) -> int | None:
    """The region whose users cannot be served at home: not judged for latency."""
    return scenario.cut_region(inc.kind, hit_of(run, inc))


# ---------------------------------------------------------------- goals


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _ops(run: Run, inc: Incident, upto: float) -> list[tuple]:
    a, b = _window(inc)
    return [o for o in run.rows("ops", a, min(b, upto)) if o[OP_END] <= upto]


def worst_p99(rows: list[tuple], kind: int, cut: int | None) -> tuple[float | None, int]:
    """The worst p99 among the regions' own users (all but `cut`); inf if a region answered none."""
    worst, where = None, -1
    for r in range(3):
        if r == cut:
            continue
        mine = [o for o in rows if o[OP_HOME] == r and o[OP_KIND] == kind]
        v = percentile([o[OP_END] - o[OP_START] for o in mine if o[OP_OK]], 99)
        if v is None:
            v = math.inf if mine else None
        if v is not None and (worst is None or v > worst):
            worst, where = v, r
    return worst, where


def _p99(kind: int):
    def measure(run: Run, inc: Incident, upto: float):
        v, _ = worst_p99(_ops(run, inc, upto), kind, cut_of(run, inc))
        if v is None:
            return None, "–"
        return v, fmt_ms(v) if v < math.inf else "∞"

    return measure


def _stale(run: Run, inc: Incident, upto: float):
    rows = _ops(run, inc, upto)
    if not rows:
        return None, "–"
    n = sum(1 for o in rows if o[OP_STALE])
    return n, fmt_int(n)


def _available(run: Run, inc: Incident, upto: float):
    rows = _ops(run, inc, upto)
    if not rows:
        return None, "–"
    v = sum(1 for o in rows if o[OP_OK]) / len(rows)
    return v, f"{v:.1%}"


def _risk(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    rows = run.rows("regions", a, min(b, upto))
    if not rows:
        return None, "–"
    n = max(r[REG_RISK] for r in rows)
    return n, fmt_int(n)


def _doomed_available(run: Run, inc: Incident, upto: float) -> bool:
    a, b = _window(inc)
    failed = sum(1 for o in _ops(run, inc, upto) if not o[OP_OK])
    return failed > (1 - lab.AVAILABLE_MIN) * run.data.get("rate", 200.0) * 1.3 * (b - a)  # more than it may fail


# The rule and fix of each goal are text.GOALS[key]; the order is lab.stage_of's.
GOALS = [
    GoalSpec("", "during", "", _window, _p99(READ), lambda v: v is not None and v <= lab.READ_P99_MAX,
             settle_extra=1.5, key="read_p99"),
    GoalSpec("", "during", "", _window, _p99(WRITE), lambda v: v is not None and v <= lab.WRITE_P99_MAX,
             settle_extra=1.5, key="write_p99"),
    GoalSpec("", "during", "", _window, _stale, lambda v: v is not None and v <= lab.RYW_MAX,
             doomed=lambda run, inc, upto: (_stale(run, inc, upto)[0] or 0) > lab.RYW_MAX, settle_extra=1.5, key="ryw"),
    GoalSpec("", "during", "", _window, _available, lambda v: v is not None and v >= lab.AVAILABLE_MIN,
             doomed=_doomed_available, settle_extra=1.5, key="available"),
    GoalSpec("", "during", "", _window, _risk, lambda v: v is not None and v <= lab.AT_RISK_MAX,
             doomed=lambda run, inc, upto: (_risk(run, inc, upto)[0] or 0) > lab.AT_RISK_MAX, settle_extra=0.5,
             key="at_risk"),
]


class GeoReplicationWorld(World):
    id = "geo_replication"
    view = "cluster"  # regions as columns of nodes, messages crossing oceans: the cluster teaches best
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "fresh", "◉"), ([EXTRA1, EXTRA2, EXTRA3], "behind", "◉"), (RED, "down", "◉"),
              (WHITE, "request"), (EXTRA2, "far"), (BLUE, "replication"), (PURPLE, "stale"), (RED, "failed"),
              (LIMIT, "limit", "┄")]
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT,)),
        "regions": Table(sort=REG_T, times=(REG_T,)),
    }
    incident_verbs = ("down", "up")

    goals = GOALS

    def __init__(self, params: dict | None = None) -> None:
        self._hits: dict[float, int] = {}
        self._goal_key: tuple | None = None
        self._goal_rows: list = []
        super().__init__(params)

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 200.0))

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        # Which region (or link) each incident hits: the events' words need it as the incident arrives.
        run = self.runs[variant]
        run.data["rate"] = self.rate
        hits = run.data.setdefault("hits", {})
        hits.update(piece.get("hits", {}))
        self._hits = hits
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        # The read p99 tile's history: each second, the worst region's p99 of the reads that started in it
        # (not the users of a region down or cut off, while that is judged, like the goal).
        p99s = run.data.setdefault("p99", {})
        by_second: dict[int, list[tuple]] = {}
        for o in tables["ops"]:
            if o[OP_KIND] == READ:
                by_second.setdefault(int(o[OP_START]), []).append(o)
        for second, rows in by_second.items():
            judged = next((i for i in reversed(run.incidents) if i.t0 <= second < _window(i)[1]), None)
            p99s[second] = worst_p99(rows, READ, cut_of(run, judged) if judged else None)[0]
        for o in tables["ops"]:
            run.add("served" if o[OP_OK] else "failed", o[OP_END])
            run.add("ops", o[OP_START])
            name = "c_failed" if not o[OP_OK] else "c_stale" if o[OP_STALE] else "c_far" if slow(o) else "c_fast"
            run.add(name, o[OP_START])
        for r in tables["regions"]:
            for i in range(3):
                run.add(f"own{i}", r[REG_T], r[REG_OWN][i])
                run.add(f"other{i}", r[REG_T], r[REG_OTHER][i])
                run.add(f"shed{i}", r[REG_T], r[REG_SHED][i])

    def goal_lines(self, variant: str, t: float):
        """The base class's, kept for the frame: the panel asks for it several times per frame."""
        run = self.runs.get(variant)
        key = (variant, t, id(run), run.end if run else 0.0)
        if self._goal_key != key:
            self._goal_key, self._goal_rows = key, super().goal_lines(variant, t)
        return self._goal_rows

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    # ---------------------------------------------------------------- incidents

    def names(self, inc: Incident, hit: int | None = None) -> dict:
        """The words for an incident: the region it hits (or the link), and its numbers."""
        hit = self._hits.get(inc.t0, 0) if hit is None else hit
        if inc.kind == "slow":
            a, b = scenario.LINKS[hit]
            return {"a": a, "b": b, "ms": inc.severity * 1000, "loss": scenario.LINK_LOSS}
        name = REGIONS[hit]
        return {"name": name, "to": FAILOVER[name], "x": inc.severity}

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(VERBS[inc.kind][0 if start else 1])

    def incident_text(self, inc: Incident, start: bool) -> str:
        words = self.names(inc)
        if start:
            return self.s(f"{inc.kind}_start", cause=self.cause(inc), **words)
        return self.s(f"{inc.kind}_end", **words)

    def warnings(self, run: Run, inc: Incident):
        """The first stale read; and, when they are reached (never earlier), how many operations failed
        and the most writes at risk."""
        out = []
        rows = run.rows("ops", *_window(inc))
        first = min((o[OP_END] for o in rows if o[OP_STALE]), default=None)
        if first is not None:
            out.append((first, self.s("warn_stale")))
        failed = [o[OP_END] for o in rows if not o[OP_OK]]
        if failed:
            out.append((max(failed), self.s("warn_failed", n=fmt_int(len(failed)))))
        samples = run.rows("regions", *_window(inc))
        worst = max(samples, key=lambda r: r[REG_RISK], default=None)
        if worst is not None and worst[REG_RISK]:
            out.append((worst[REG_T], self.s("warn_risk", n=fmt_int(worst[REG_RISK]))))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    # ---------------------------------------------------------------- what the pictures share

    def sample_at(self, run: Run, t: float) -> tuple | None:
        rows = run.rows("regions", t - 0.5, t + 1e-9)
        return rows[-1] if rows else None

    def busy(self, run: Run, t: float) -> list[float]:
        """Each region's utilisation over the last second."""
        rows = run.rows("regions", t - 1.0, t + 1e-9)
        if not rows:
            return [0.0] * 3
        return [sum(r[REG_BUSY][i] for r in rows) / len(rows) for i in range(3)]

    def region_colours(self, run: Run, t: float) -> list:
        s = self.sample_at(run, t)
        if s is None:
            return [BLUE] * 3
        return [behind_colour(s[REG_BEHIND][i]) if s[REG_UP][i] else RED for i in range(3)]

    def recent(self, run: Run, t: float, seconds: float) -> list[tuple]:
        span = run.max_dur.get("ops", 0.0)
        return [o for o in run.rows("ops", t - seconds - span, t) if t - seconds <= o[OP_END] < t]

    def state_at(self, variant: str, t: float) -> tuple[str, tuple[int, int, int]]:
        """The words under the cluster: which region is in trouble, and what the users get."""
        run = self.runs.get(variant)
        if run is None:
            return self.screen.STATES["healthy"], GREEN
        inc = self.incident_at(variant, t)
        last = self.recent(run, t, 1.0)
        stale = sum(1 for o in last if o[OP_STALE])
        if inc is not None:
            words = self.names(inc, hit_of(run, inc))
            text = self.s(f"state_{inc.kind}", **words)
            colour = RED if inc.kind in ("down", "partition") else EXTRA2
        else:
            p99, _ = worst_p99([o for o in last if o[OP_KIND] == READ], READ, None)
            text, colour = self.s("state_ok", p99=fmt_ms(p99) if p99 not in (None, math.inf) else "–"), GREEN
        if stale:
            text, colour = f"{text} · {self.s('state_stale', n=stale)}", PURPLE
        return text, colour

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        inc = self.incident_at(variant, t)
        judged = next((i for i in reversed(run.incidents) if i.t0 <= t < _window(i)[1]), None)
        cut = cut_of(run, judged) if judged else None  # like the goal: not its users, until it is judged

        def p99_of(a: float, b: float) -> float | None:
            rows = [o for o in self.recent(run, b, b - a) if o[OP_KIND] == READ]
            return worst_p99(rows, READ, cut)[0]

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.READ_P99_MAX else "warn" if v > lab.READ_P99_MAX / 2 else "ok"

        def p99_s(s: int):
            v = run.data.get("p99", {}).get(s)
            return min(v or 0.0, 0.3), p99_state(v)

        def stale_s(s: int):
            v = run.series("c_stale", s, s + 1)[0]
            return v, "bad" if v else "ok"

        def avail_of(a: int, b: int) -> float | None:
            done = sum(run.series("served", a, b)) + sum(run.series("failed", a, b))
            return sum(run.series("served", a, b)) / done if done else None

        def avail_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.AVAILABLE_MIN else "warn" if v < 1 else "ok"

        def avail_s(s: int):
            v = avail_of(s, s + 1)
            return (v if v is not None else 1.0), avail_state(v)

        p99 = p99_of(t - 5, t)
        last5 = self.recent(run, t, 5.0)
        stale = sum(1 for o in last5 if o[OP_STALE])
        avail = sum(1 for o in last5 if o[OP_OK]) / len(last5) if last5 else None
        tiles = [
            Tile(self.s("tile_p99"), fmt_ms(p99) if p99 != math.inf else "∞", f"≤{lab.READ_P99_MAX * 1000:.0f}ms",
                 p99_state(p99), history(run, t, p99_s)),
            Tile(self.s("tile_stale"), str(stale), "=0", "bad" if stale else "ok", history(run, t, stale_s)),
            Tile(self.s("tile_available"), "–" if avail is None else f"{avail:.1%}", f"≥{lab.AVAILABLE_MIN:.0%}",
                 avail_state(avail), history(run, t, avail_s)),
        ]
        s = int(t) - 1
        bars = [Bar(name, [(run.series(f"own{i}", s, s + 1)[0], WHITE), (run.series(f"other{i}", s, s + 1)[0], EXTRA2),
                           (run.series(f"shed{i}", s, s + 1)[0], RED)])
                for i, name in enumerate(REGIONS)]
        headline, colour = self._headline(variant, run, t, stale, inc)
        top = max(CAPACITY * 1.15, max(sum(v for v, _ in b.segments) for b in bars) * 1.05)
        return Traffic(tiles, bars, CAPACITY, self.s("limit", limit=CAPACITY), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=top)

    def _headline(self, variant: str, run: Run, t: float, stale: int, inc: Incident | None):
        if stale:
            return self.s("head_stale", n=stale), PURPLE
        busy = self.busy(run, t)
        hottest = max(range(3), key=lambda i: busy[i])
        if inc is not None:
            words = self.names(inc, hit_of(run, inc))
            colour = RED if inc.kind in ("down", "partition") else EXTRA2
            return self.s(f"head_{inc.kind}", busiest=REGIONS[hottest], util=busy[hottest], **words), colour
        last = [o for o in self.recent(run, t, 5.0) if o[OP_KIND] == READ]
        p99, where = worst_p99(last, READ, None)
        if p99 is not None and p99 > lab.READ_P99_MAX:
            return self.s("head_far", region=REGIONS[where], p99=fmt_ms(p99) if p99 < math.inf else "∞"), EXTRA2
        return self.s("head_ok", p99=fmt_ms(p99)), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t, busy=60)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(colour, run.hist.get(name, [])) for name, colour in
                (("c_fast", WHITE), ("c_far", EXTRA2), ("c_stale", PURPLE), ("c_failed", RED))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_nodes"), self.s("note_chart")]


WORLD = GeoReplicationWorld
