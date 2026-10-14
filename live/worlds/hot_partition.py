"""World for lab hot_partition. Its words are in labs/hot_partition/text/<lang>.py."""

from __future__ import annotations

from dataclasses import replace

from labs.hot_partition import lab
from labs.hot_partition.api import CAPACITY, FAN, FOLD, HOT, PARTITIONS, PLAIN
from labs.hot_partition.scenario import SAMPLE, THROTTLED
from live.canvas import BLUE, EXTRA1, EXTRA2, LIMIT, MUTED, PURPLE, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, fmt_ms, history, percentile,
)

OP_START, OP_END, OP_WRITE, OP_OK, OP_REQS, OP_HOT = range(6)
REQ_T, REQ_P, REQ_KIND, REQ_OK, REQ_INC = range(5)
LOAD_T, LOAD_BUSY, LOAD_REQS, LOAD_REFUSED = range(4)
AUD_T, AUD_INC, AUD_ACKED, AUD_STORED, AUD_SENT = range(5)
HOT_T, HOT_INC, HOT_KEY, HOT_P = range(4)

KIND_NAMES = {PLAIN: "plain", HOT: "hot", FAN: "fan", FOLD: "fold"}
KIND_COLOURS = {PLAIN: WHITE, HOT: PURPLE, FAN: EXTRA2, FOLD: BLUE}
CHART = ("c_plain", "c_hot", "c_fan", "c_refused")  # the busiest partition's requests each second

def util_colour(u: float):
    """A partition's colour from its utilisation."""
    return BLUE if u < 0.5 else EXTRA1 if u < 0.7 else EXTRA2 if u < lab.BUSY_MAX else RED


def deficit(row: tuple) -> int:
    """Increments the store does not hold (acknowledged, but not in any key keys_of names), plus any
    it holds that were never sent."""
    return max(0, row[AUD_ACKED] - row[AUD_STORED]) + max(0, row[AUD_STORED] - row[AUD_SENT])


# ---------------------------------------------------------------- goals


def _hot_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 + lab.SETTLE_IN, max(inc.t1, inc.t0 + lab.SETTLE_IN + SAMPLE)


def _op_window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _audit_window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER_END + 1.0


def _cool_window(inc: Incident) -> tuple[float, float]:
    return inc.t1 + lab.AFTER_START, inc.t1 + lab.AFTER_END


def _busiest(run: Run, inc: Incident, upto: float):
    a, b = _hot_window(inc)
    rows = [r for r in run.rows("load", a, min(b, upto)) if r[LOAD_T] + SAMPLE <= min(b, upto) + 1e-9]
    if not rows:
        return None, "–"
    v = sum(max(r[LOAD_BUSY]) for r in rows) / len(rows)
    return v, f"{v:.0%}"


def _ops(run: Run, inc: Incident, upto: float) -> list[tuple]:
    a, b = _op_window(inc)
    return [o for o in run.rows("ops", a, min(b, upto)) if o[OP_END] <= upto]


def _throttled(run: Run, inc: Incident, upto: float):
    ops = _ops(run, inc, upto)
    if not ops:
        return None, "–"
    v = sum(1 for o in ops if o[OP_OK] == THROTTLED) / len(ops)
    return v, f"{v:.1%}"


def _doomed_throttled(run: Run, inc: Incident, upto: float) -> bool:
    refused = sum(1 for o in _ops(run, inc, upto) if o[OP_OK] == THROTTLED)
    return refused > lab.THROTTLED_MAX * max(1, run.count("ops", *_op_window(inc)))


def _p99(run: Run, inc: Incident, upto: float):
    v = percentile([o[OP_END] - o[OP_START] for o in _ops(run, inc, upto) if o[OP_OK] != THROTTLED], 99)
    return (None, "–") if v is None else (v, fmt_ms(v))


def _lost_n(run: Run, inc: Incident, upto: float) -> int | None:
    """The most increments missing in two audits in a row (a count in flight between two keys while
    sub-keys are folded back is missing for an instant; a lost one is missing for good)."""
    a, b = _audit_window(inc)
    rows = [r for r in run.rows("audits", a, min(b, upto + 1e-9)) if r[AUD_INC] == inc.index]
    if not rows:
        return None
    return max((min(deficit(x), deficit(y)) for x, y in zip(rows, rows[1:])), default=0)


def _correct(run: Run, inc: Incident, upto: float):
    n = _lost_n(run, inc, upto)
    return (None, "–") if n is None else (n, fmt_int(n))


def _fanin(run: Run, inc: Incident, upto: float):
    a, b = _cool_window(inc)
    ops = [o for o in run.rows("ops", a, min(b, upto)) if o[OP_END] <= upto]
    if not ops:
        return None, "–"
    v = sum(o[OP_REQS] for o in ops) / len(ops)
    return v, f"{v:.2f}x"


# The rule and fix of each goal are text.GOALS[key]; the order is lab.stage_of's.
GOALS = [
    GoalSpec("", "during", "", _hot_window, _busiest, lambda v: v is not None and v < lab.BUSY_MAX,
             settle_extra=0.5, key="busiest"),
    GoalSpec("", "during", "", _op_window, _throttled, lambda v: v is not None and v <= lab.THROTTLED_MAX,
             doomed=_doomed_throttled, settle_extra=1.0, key="throttled"),
    GoalSpec("", "during", "", _op_window, _p99, lambda v: v is not None and v <= lab.P99_MAX,
             settle_extra=1.0, key="p99"),
    GoalSpec("", "after", "", _audit_window, _correct, lambda v: v == 0,
             doomed=lambda run, inc, upto: bool(_lost_n(run, inc, upto)), settle_extra=0.5, key="correct"),
    GoalSpec("", "after", "", _cool_window, _fanin, lambda v: v is not None and v <= lab.FANIN_MAX,
             settle_extra=1.0, key="fanin"),
]


class HotPartitionWorld(World):
    id = "hot_partition"
    view = "cluster"  # one partition turning red while the others idle shows best as nodes
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(BLUE, "cool", "◉"), ([EXTRA1, EXTRA2], "busy", "◉"), (RED, "melting", "◉"),
              (WHITE, "request"), (PURPLE, "hot_key"), (EXTRA2, "fan_in"), (BLUE, "cached"),
              (RED, "throttled"), (LIMIT, "limit", "┄")]
    tables = {
        "ops": Table(sort=OP_START, times=(OP_START, OP_END)),
        "reqs": Table(sort=REQ_T, times=(REQ_T,)),
        "load": Table(sort=LOAD_T, times=(LOAD_T,)),
        "audits": Table(sort=AUD_T, times=(AUD_T,)),
        "hots": Table(sort=HOT_T, times=(HOT_T,)),
    }
    goals = GOALS
    chart_top = CAPACITY * 1.2

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 120.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["ops"]:
            run.add("ops", o[OP_START])
            run.add("served" if o[OP_OK] != THROTTLED else "failed", o[OP_END])
            run.add("requests", o[OP_START], o[OP_REQS])
        for r in tables["reqs"]:
            name = f"p{r[REQ_P]}_{KIND_NAMES[r[REQ_KIND]] if r[REQ_OK] else 'refused'}"
            run.add(name, r[REQ_T])
        # The chart: each second, the requests on the partition that was busiest that second.
        for s in range(int(piece["start"]), int(piece["end"])):
            p = max(range(PARTITIONS), key=lambda q: sum(run.series(f"p{q}_{k}", s, s + 1)[0]
                                                         for k in ("plain", "hot", "fan", "fold", "refused")))
            for name, part in zip(CHART, ("plain", "hot", "fan", "refused")):
                n = run.series(f"p{p}_{part}", s, s + 1)[0]
                if part == "plain":
                    n += run.series(f"p{p}_fold", s, s + 1)[0]
                run.add(name, s, n)
        # Name the key and its partition in the incident's events (the incident only knows its kind).
        keys = run.data.setdefault("keys", {})
        for h in tables["hots"]:
            keys[h[HOT_INC]] = (h[HOT_KEY], h[HOT_P])
            for k, e in enumerate(run.timeline):
                if e.kind in ("start", "end") and e.incident == h[HOT_INC]:
                    inc = run.incidents[e.incident]
                    run.timeline[k] = replace(e, text=self._incident_text(inc, e.kind == "start", h[HOT_KEY], h[HOT_P]))

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def _incident_text(self, inc: Incident, start: bool, key: str | None, p: int | None) -> str:
        if not start:
            return self.s("end", key=key) if key else self.s("end_plain")
        if key:
            return self.s(f"{inc.kind}_start", key=key, p=p, rate=inc.severity, cause=self.cause(inc))
        return self.s("start_plain", rate=inc.severity, cause=self.cause(inc))

    def incident_text(self, inc: Incident, start: bool) -> str:
        return self._incident_text(inc, start, None, None)

    def warnings(self, run: Run, inc: Incident):
        ops = run.rows("ops", *_op_window(inc))
        refused = sum(1 for o in ops if o[OP_OK] == THROTTLED)
        return [(inc.t1, self.s("warn_throttled", n=fmt_int(refused)))] if refused else []

    def key_of(self, run: Run, index: int) -> tuple[str, int] | None:
        return run.data.get("keys", {}).get(index)

    def incident_at(self, variant: str, t: float) -> Incident | None:
        """The incident whose key is hot at t (with a second of its ramp down)."""
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1 + 2.0), None)

    # ---------------------------------------------------------------- what the pictures share

    def utils(self, variant: str, t: float) -> list[float]:
        """Each partition's utilisation over the last second."""
        run = self.runs.get(variant)
        rows = run.rows("load", t - 1.0, t - SAMPLE + 1e-9) if run else []
        if not rows:
            return [0.0] * PARTITIONS
        return [sum(r[LOAD_BUSY][p] for r in rows) / len(rows) for p in range(PARTITIONS)]

    def per_partition(self, variant: str, t: float) -> list[dict[str, int]]:
        """Requests each partition got in the last second, by what they were for."""
        run = self.runs[variant]
        out = [{"plain": 0, "hot": 0, "fan": 0, "fold": 0, "refused": 0} for _ in range(PARTITIONS)]
        for r in run.rows("reqs", t - 1.0, t):
            out[r[REQ_P]][KIND_NAMES[r[REQ_KIND]] if r[REQ_OK] else "refused"] += 1
        return out

    def spread(self, variant: str, t: float) -> int:
        """Partitions the hot key's writes and reads went to in the last second."""
        run = self.runs[variant]
        inc = self.incident_at(variant, t)
        if inc is None:
            return 0
        return len({r[REQ_P] for r in run.rows("reqs", t - 1.0, t) if r[REQ_INC] == inc.index and r[REQ_KIND] == HOT})

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        utils = self.utils(variant, t)
        busiest = max(utils)

        def busy_state(v: float) -> str:
            return "bad" if v >= lab.BUSY_MAX else "warn" if v >= 0.7 else "ok"

        def busy_s(s: int):
            v = max(self.utils(variant, s + 1))
            return v, busy_state(v)

        def refused_share(a: float, b: float) -> float | None:
            ops = run.series("ops", int(a), int(b))
            failed = run.series("failed", int(a), int(b))
            return sum(failed) / sum(ops) if sum(ops) else None

        refused = refused_share(t - 5, t)

        def refused_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.THROTTLED_MAX else "warn" if v > 0 else "ok"

        def refused_s(s: int):
            v = refused_share(s, s + 1)
            return (v or 0.0), refused_state(v)

        span = run.max_dur.get("ops", 0.0)

        def p99_of(a: float, b: float) -> float | None:
            return percentile([o[OP_END] - o[OP_START] for o in run.rows("ops", a - span, b)
                               if a <= o[OP_END] < b and o[OP_OK] != THROTTLED], 99)

        p99 = p99_of(t - 5, t)

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.P99_MAX else "warn" if v > lab.P99_MAX / 2 else "ok"

        def p99_s(s: int):
            v = p99_of(s, s + 1)
            return min(v or 0.0, 0.3), p99_state(v)

        tiles = [
            Tile(self.s("tile_busiest"), f"{busiest:.0%}", f"<{lab.BUSY_MAX:.0%}", busy_state(busiest),
                 history(run, t, busy_s)),
            Tile(self.s("tile_throttled"), "–" if refused is None else f"{refused:.1%}",
                 f"≤{lab.THROTTLED_MAX:.0%}", refused_state(refused), history(run, t, refused_s)),
            Tile(self.s("tile_p99"), fmt_ms(p99), f"≤{lab.P99_MAX * 1000:.0f}ms", p99_state(p99),
                 history(run, t, p99_s)),
        ]
        parts = self.per_partition(variant, t)
        bars = [Bar(f"p{p}", [(float(c["plain"] + c["fold"]), WHITE), (float(c["hot"]), PURPLE),
                              (float(c["fan"]), EXTRA2), (float(c["refused"]), RED)])
                for p, c in enumerate(parts)]
        hottest = max(range(PARTITIONS), key=lambda p: utils[p])
        inc = self.incident_at(variant, t)
        named = self.key_of(run, inc.index) if inc else None
        if parts[hottest]["refused"]:
            headline = self.s("head_refused", p=hottest, n=parts[hottest]["refused"])
            colour = RED
        elif named is not None and self.spread(variant, t) > 1:
            headline, colour = self.s("head_spread", key=named[0], n=self.spread(variant, t)), PURPLE
        elif named is not None:
            headline, colour = self.s("head_one", key=named[0], p=named[1]), EXTRA2
        else:
            headline, colour = self.s("head_ok", util=busiest), MUTED
        top = max(CAPACITY * 1.3, max(sum(c.values()) for c in parts) * 1.05)
        return Traffic(tiles, bars, CAPACITY, self.s("limit", limit=CAPACITY), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=top)

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "ops", OP_START, OP_END, OP_OK, t, busy=40)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(colour, run.hist.get(name, [])) for name, colour in zip(CHART, (WHITE, PURPLE, EXTRA2, RED))]

    def chart_limit(self):
        return CAPACITY, self.s("chart_limit", limit=CAPACITY)

    def legend_notes(self) -> list[str]:
        return [self.s("note_nodes"), self.s("note_chart")]


WORLD = HotPartitionWorld
