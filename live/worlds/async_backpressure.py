"""World for lab async_backpressure. Its words are in labs/async_backpressure/text/<lang>.py."""

from __future__ import annotations

import math

from core.i18n import strings
from labs.async_backpressure import lab
from labs.async_backpressure.api import BASE_MEMORY, MEMORY_LIMIT, SIZE
from labs.async_backpressure.scenario import LOST, PENDING, SHED, TICK, WRITTEN
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, fmt_ms, history, percentile,
)

INCIDENT_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

(T_T, T_ARR, T_READ, T_WR, T_SHED, T_LUP, T_LOOM, T_LHIGH, T_OOMS, T_PEAK, T_MEM, T_UP, T_RAW, T_PARSED,
 T_ENR, T_ALIVE, T_WRITES, T_WROTE, T_ENRICHING) = range(19)
E_ARR, E_ID, E_READ, E_PARSED, E_ENR, E_END, E_OUT, E_PRIO, E_WHERE = range(9)
W_START, W_END, W_N, W_OK = range(4)

WAITED = (0.25, 1.0, 4.0)  # seconds an event has waited before it turns light, mid, deep orange
PENDING_SPAN = 40.0  # an event still on its way after this long is not drawn

_s = strings("async_backpressure")  # one of the lab's STRINGS, for the goal measures below


def lost(r: tuple) -> int:
    """Events lost silently in a tick: dropped by the upstream, killed with the process, or HIGH shed."""
    return r[T_LUP] + r[T_LOOM] + r[T_LHIGH]


def wait_colour(waited: float):
    """How long an event has waited so far: white, then deeper orange."""
    if waited < WAITED[0]:
        return WHITE
    return EXTRA1 if waited < WAITED[1] else EXTRA2 if waited < WAITED[2] else EXTRA3


def outcome_colour(e: tuple):
    return GREEN if e[E_OUT] == WRITTEN else MUTED if e[E_OUT] == SHED else RED


def compact(n: float) -> str:
    """A count short enough for a label: 12, 950, 4.3k, 12k."""
    return fmt_int(n) if n < 1000 else f"{n / 1000:.1f}k" if n < 10_000 else f"{n / 1000:.0f}k"


def capacity_at(run: Run, t: float) -> float:
    """Events/s the slowest service can take at t, at best."""
    for inc in reversed(run.incidents):
        if inc.t0 <= t < inc.t1:
            return lab.capacity(inc.kind, inc.severity)
        if inc.t1 <= t:
            break
    return lab.capacity(None, 1.0)


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0 - 1.0


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, max(inc.t1, inc.t0 + 1.0)


def _busy(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _after(inc: Incident) -> tuple[float, float]:
    a = inc.t1 + lab.RECOVER
    return a, a + lab.RECOVER_WINDOW


def _ticks(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    return run.rows("ticks", a + 1e-9, min(b, upto) + 1e-9)  # a tick at t covers (t - TICK, t]


def _baseline(run: Run, inc: Incident, upto: float):
    rows = _ticks(run, *_before(inc), upto)
    arrived = sum(r[T_ARR] for r in rows)
    if not arrived:
        return None, "–"
    v = sum(r[T_WR] for r in rows) / arrived
    return v, f"{min(v, 1.0):.0%}"


def _ooms(run: Run, inc: Incident, upto: float):
    rows = _ticks(run, *_busy(inc), upto)
    if not rows:
        return None, "–"
    n = sum(r[T_OOMS] for r in rows)
    return n, _s("count", n=n)


def _lost(run: Run, inc: Incident, upto: float):
    rows = _ticks(run, *_busy(inc), upto)
    if not rows:
        return None, "–"
    n = sum(lost(r) for r in rows)
    return n, _s("count", n=n)


def _peak(run: Run, inc: Incident, upto: float):
    rows = _ticks(run, *_busy(inc), upto)
    if not rows:
        return None, "–"
    v = max(r[T_PEAK] for r in rows) / MEMORY_LIMIT
    return v, f"{v:.0%}"


def _throughput(run: Run, inc: Incident, upto: float):
    """Events written vs what was possible: what arrived, or the slowest service's best if less;
    whole seconds inside the incident, so both sides count the same time."""
    a, b = _during(inc)
    a, b = float(math.ceil(a)), float(math.floor(min(b, upto)))
    if b - a < 1.0:
        return None, "–"
    rows = _ticks(run, a, b, upto)
    cap = lab.capacity(inc.kind, inc.severity)
    arrived: dict[int, int] = {}
    for r in rows:
        k = math.ceil(r[T_T] - 1e-6) - 1
        arrived[k] = arrived.get(k, 0) + r[T_ARR]
    possible = sum(min(n, cap) for n in arrived.values())
    if possible < 1.0:
        return None, "–"
    v = sum(r[T_WR] for r in rows) / possible
    return v, f"{min(v, 9.99):.0%}"


def _p99_after(run: Run, inc: Incident, upto: float):
    """End-to-end p99 of the events that arrived after the incident: written ones by their wait, lost
    ones (or still waiting at the end) as forever; shed LOW events do not count."""
    a, b = _after(inc)
    waits = []
    for e in run.rows("events", a, min(b, upto)):
        end = e[E_END]
        if e[E_OUT] == SHED:
            continue
        if e[E_OUT] == WRITTEN and end <= upto:
            waits.append(end - e[E_ARR])
        elif e[E_OUT] == LOST and end <= upto or e[E_OUT] == PENDING and math.isinf(upto):
            waits.append(math.inf)
    v = percentile(waits, 99)
    if v is None:
        return None, "–"
    return v, "∞" if math.isinf(v) else fmt_ms(v)


def _doomed_count(measure):
    return lambda run, inc, upto: (measure(run, inc, upto)[0] or 0) > 0


def _peak_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _peak(run, inc, upto)
    return v is not None and v > lab.PEAK_MAX


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, key="baseline"),
    GoalSpec("", "during", "", _busy, _ooms, lambda v: v == 0, doomed=_doomed_count(_ooms),
             settle_extra=1.0, key="oom"),
    GoalSpec("", "during", "", _busy, _lost, lambda v: v == 0, doomed=_doomed_count(_lost),
             settle_extra=1.0, key="lost"),
    GoalSpec("", "during", "", _busy, _peak, lambda v: v is not None and v <= lab.PEAK_MAX,
             doomed=_peak_doomed, settle_extra=1.0, key="peak"),
    GoalSpec("", "during", "", _during, _throughput, lambda v: v is None or v >= lab.THROUGHPUT_MIN,
             settle_extra=1.0, key="throughput"),
    GoalSpec("", "after", "", _after, _p99_after, lambda v: v is not None and v < lab.P99_MAX,
             settle_extra=lab.SETTLE, key="p99"),
]


class AsyncBackpressureWorld(World):
    id = "async_backpressure"
    view = "pipeline"
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "event"), ([EXTRA1, EXTRA2, EXTRA3], "waiting"),
              (GREEN, "written"), (MUTED, "shed"), (RED, "lost"), (LIMIT, "limit", "┄"),
              (INCIDENT_KEY, "incident", "█")]
    chart_top = 100.0
    tables = {
        "ticks": Table(sort=T_T, times=(T_T,)),
        "events": Table(sort=E_ARR, times=(E_ARR, E_END)),
        "writes": Table(sort=W_START, times=(W_START, W_END)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 1000.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        share = 100.0 / MEMORY_LIMIT * TICK  # per tick: a per-second average of the memory, in %
        for r in tables["ticks"]:
            t = r[T_T] - 1e-6  # a tick at t covers (t - TICK, t]
            run.add("arrived", t, r[T_ARR])
            run.add("written", t, r[T_WR])
            run.add("shed", t, r[T_SHED])
            run.add("lost", t, lost(r))
            run.add("ooms", t, r[T_OOMS])
            if r[T_ALIVE]:
                run.add("m_base", t, BASE_MEMORY * share)
            for k, col in enumerate((T_RAW, T_PARSED, T_ENR)):
                run.add(f"m_{k}", t, r[col] * SIZE[k] * share)
            s = int(t)
            peak = run.hist.setdefault("peak", [])
            if s >= len(peak):
                peak.extend([0.0] * (s + 1 - len(peak)))
            peak[s] = max(peak[s], r[T_PEAK] / MEMORY_LIMIT)

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", n=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        rows = run.rows("ticks", inc.t0, inc.t1 + lab.AFTER)
        out = []
        ooms = sum(r[T_OOMS] for r in rows)
        if ooms:
            out.append((inc.t1, self.s("warn_oom", n=ooms, lost=sum(r[T_LOOM] for r in rows))))
        up = sum(r[T_LUP] for r in rows)
        if up:
            out.append((inc.t1, self.s("warn_upstream", n=up)))
        shed = sum(r[T_SHED] for r in rows)
        if shed:
            out.append((inc.t1, self.s("warn_shed", n=shed)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def tick_at(self, run: Run, t: float) -> tuple | None:
        """The last tick at or before t."""
        rows = run.rows("ticks", t - 1.0, t + 1e-9)
        return rows[-1] if rows else None

    def pending(self, run: Run, t: float) -> list[tuple]:
        """Traced events that have arrived by t and are still on their way at t."""
        return [e for e in run.rows("events", t - PENDING_SPAN, t + 1e-9)
                if e[E_END] is None or e[E_END] > t]

    def ended(self, run: Run, a: float, b: float) -> list[tuple]:
        """Traced events whose fate (written, shed, lost) came in [a, b)."""
        span = min(run.max_dur.get("events", 0.0), PENDING_SPAN)
        return [e for e in run.rows("events", a - span, b) if e[E_END] is not None and a <= e[E_END] < b]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        s = int(t)
        tick = self.tick_at(run, t)
        mem = tick[T_MEM] / MEMORY_LIMIT if tick is not None else None

        def mem_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.PEAK_MAX else "warn" if v > lab.PEAK_MAX * 0.8 else "ok"

        def mem_s(k: int):
            v = run.series("peak", k, k + 1)[0]
            return v, mem_state(v)

        lost10 = sum(run.series("lost", s - 10, s))

        def lost_s(k: int):
            v = run.series("lost", k, k + 1)[0]
            return v, "bad" if v else "ok"

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.P99_MAX / 2 else "ok"

        def waits(a: float, b: float) -> list[float]:
            return [e[E_END] - e[E_ARR] for e in self.ended(run, a, b) if e[E_OUT] == WRITTEN]

        def p99_s(k: int):
            v = percentile(waits(k, k + 1), 99)
            return (v or 0.0), p99_state(v)

        p99 = percentile(waits(t - 5, t), 99)
        tiles = [
            Tile(self.s("tile_memory"), "–" if mem is None else f"{mem:.0%}", f"≤{lab.PEAK_MAX:.0%}",
                 mem_state(mem), history(run, t, mem_s)),
            Tile(self.s("tile_lost"), fmt_int(lost10), "=0", "bad" if lost10 else "ok", history(run, t, lost_s)),
            Tile(self.screen.STATS["p99"], fmt_ms(p99), f"<{fmt_ms(lab.P99_MAX)}", p99_state(p99),
                 history(run, t, p99_s)),
        ]

        def last(name: str) -> float:  # writes land in lumps of up to 1,000: average 3 s
            return sum(run.series(name, s - 3, s)) / 3

        bars = [
            Bar(self.s("bar_arrived"), [(last("arrived"), WHITE)]),
            Bar(self.s("bar_written"), [(last("written"), GREEN)]),
            Bar(self.s("bar_dropped"), [(last("shed"), MUTED), (last("lost"), RED)]),
        ]
        cap = capacity_at(run, t)
        top = max(self.rate * 1.6, last("arrived") * 1.05, last("written") * 1.05, cap * 1.1, 1.0)
        headline, colour = self._headline(variant, run, t, tick)
        return Traffic(tiles, bars, cap, self.s("limit", n=compact(cap)), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=top)

    def _headline(self, variant: str, run: Run, t: float, tick: tuple | None):
        s = int(t)
        if tick is not None and not tick[T_ALIVE]:
            killed = sum(r[T_LOOM] for r in run.rows("ticks", t - 10, t + 1e-9))
            return self.s("head_restarting", n=killed), RED
        up = sum(r[T_LUP] for r in run.rows("ticks", t - 5, t + 1e-9))
        if up:
            return self.s("head_upstream", n=up), RED
        if tick is None:
            return "", MUTED
        mem = tick[T_MEM] / MEMORY_LIMIT
        if mem > lab.PEAK_MAX:
            return self.s("head_memory", pct=f"{mem:.0%}"), EXTRA2
        shed = sum(run.series("shed", s - 3, s)) / 3
        if shed:
            return self.s("head_shed", n=shed), MUTED
        if tick[T_UP] > 1000:
            return self.s("head_paused", n=tick[T_UP]), EXTRA2
        inc = self.incident_at(variant, t)
        if inc is not None:
            return self.s(f"head_{inc.kind}"), BLUE
        writes = run.rows("writes", t - 2, t + 1e-9)
        ok = [w[W_N] for w in writes if w[W_OK]]
        return self.s("head_ok", n=round(sum(ok) / len(ok)) if ok else 0), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        tick = self.tick_at(run, t)
        recent = [e[E_END] - e[E_ARR] for e in self.ended(run, t - 5, t) if e[E_OUT] == WRITTEN]
        written, shed, gone = run.total("written", t), run.total("shed", t), run.total("lost", t)
        waiting = 0 if tick is None else tick[T_UP] + tick[T_RAW] + tick[T_PARSED] + tick[T_ENR]
        return [
            (self.s("stat_written"), fmt_int(written), GREEN),
            (self.s("stat_lost"), fmt_int(gone), RED if gone else MUTED),
            (self.s("stat_shed"), fmt_int(shed), MUTED),
            (self.screen.STATS["waiting"], fmt_int(waiting), EXTRA2 if waiting > self.rate else WHITE),
            (self.screen.STATS["p99"], fmt_ms(percentile(recent, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(DIM, run.hist.get("m_base", [])), (WHITE, run.hist.get("m_0", [])),
                (EXTRA1, run.hist.get("m_1", [])), (EXTRA2, run.hist.get("m_2", []))]

    def chart_limit(self):
        return lab.PEAK_MAX * 100, f"{lab.PEAK_MAX:.0%}"

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = AsyncBackpressureWorld
