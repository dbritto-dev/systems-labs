"""World for lab rate_limiting. Its words are in labs/rate_limiting/text/<lang>.py."""

from __future__ import annotations

from labs.rate_limiting import lab
from labs.rate_limiting.scenario import FAILED, LIMITED, SERVED
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World,
    fmt_int, fmt_ms, history, percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_CLIENT, REQ_OUTCOME, REQ_FLOOD = range(6)
FLOOD_KEY = (110, 44, 56)  # the legend swatch for the shaded floods


def _peak(rows: list[tuple]) -> float:
    """The most requests one client got through in any 1 s, as a multiple of its rate."""
    by: dict[int, list[float]] = {}
    for r in rows:
        if r[REQ_OUTCOME] != LIMITED:
            by.setdefault(r[REQ_CLIENT], []).append(r[REQ_START])
    best = 0
    for times in by.values():  # rows come sorted by start
        j = 0
        for i, t in enumerate(times):
            while t - times[j] >= 1.0:
                j += 1
            best = max(best, i - j + 1)
    return best / lab.CLIENT_RATE


def _served(rows: list[tuple]) -> float | None:
    return sum(r[REQ_OUTCOME] == SERVED for r in rows) / len(rows) if rows else None


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = _served([r for r in run.rows("requests", a, min(b, upto)) if r[REQ_END] <= upto])
    return (None, "–") if v is None else (v, f"{v:.0%}")


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _limited(run: Run, inc: Incident, upto: float):
    flood = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_FLOOD]]
    if not flood:
        return None, "–"
    v = sum(r[REQ_OUTCOME] == LIMITED for r in flood) / len(flood)
    return v, f"{v:.0%}"


def _flood_peak(run: Run, inc: Incident, upto: float):
    flood = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_FLOOD]]
    if not flood:
        return None, "–"
    v = _peak(flood)
    return v, f"{v:.1f}x"


def _peak_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _flood_peak(run, inc, upto)
    return v is not None and v > lab.PEAK_MAX  # the peak so far can only grow


def _others(run: Run, inc: Incident, upto: float):
    rows = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if not r[REQ_FLOOD] and r[REQ_END] <= upto]
    v = _served(rows)
    return (None, "–") if v is None else (v, f"{v:.0%}")


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER_WINDOW


def _after_served(run: Run, inc: Incident, upto: float):
    """Served share just after the flood, for the clients that did not flood (a client that
    just flooded has an empty bucket, and is right to wait for it to refill)."""
    flooders = {r[REQ_CLIENT] for r in run.rows("requests", inc.t0, inc.t1) if r[REQ_FLOOD]}
    a, b = _after(inc)
    rows = [r for r in run.rows("requests", a, min(b, upto))
            if r[REQ_END] <= upto and r[REQ_CLIENT] not in flooders]
    v = _served(rows)
    return (None, "–") if v is None else (v, f"{v:.0%}")


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, key="baseline"),
    GoalSpec("", "during", "", _during, _limited,
             lambda v: v is not None and v >= lab.LIMITED_MIN, key="limited"),
    GoalSpec("", "during", "", _during, _flood_peak,
             lambda v: v is not None and v <= lab.PEAK_MAX, doomed=_peak_doomed, key="peak"),
    GoalSpec("", "during", "", _during, _others,
             lambda v: v is not None and v >= lab.OTHERS_MIN, settle_extra=1.0, key="others"),
    GoalSpec("", "after", "", _after, _after_served,
             lambda v: v is not None and v >= lab.SERVED_MIN, settle_extra=1.0, key="served"),
]


class RateLimitWorld(World):
    id = "rate_limiting"
    view = "lanes"
    stage_colours = (RED, EXTRA2, EXTRA1, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "normal"), (EXTRA2, "flooding"), (EXTRA3, "limited"),
              (RED, "failed"), (GREEN, "served"), (LIMIT, "limit", "┄"), (FLOOD_KEY, "flood", "█")]
    incident_verbs = ("flood", "calm")
    tables = {"requests": Table(sort=REQ_START, times=(REQ_START, REQ_END))}
    goals = GOALS
    chart_top = 450.0

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        per_client: dict[tuple[int, int], int] = {}
        for r in tables["requests"]:
            start, outcome, flood = r[REQ_START], r[REQ_OUTCOME], r[REQ_FLOOD]
            run.add("ask", start)
            run.add("ask_flood" if flood else "ask_normal", start)
            match outcome:
                case 0:  # SERVED
                    run.add("ok_flood" if flood else "ok_normal", start)
                    run.add("served", r[REQ_END])
                case 1:  # LIMITED
                    run.add("limited", r[REQ_END])
                    run.add("limited_s", start)
                case _:  # FAILED: the backend turned it away
                    run.add("failed_s", start)
                    run.add("failed", r[REQ_END])
            if outcome != LIMITED:
                run.add("sent", start)
                key = (int(start), r[REQ_CLIENT])
                per_client[key] = per_client.get(key, 0) + 1
            if not flood:
                run.add("others", start)
                if outcome == SERVED:
                    run.add("others_ok", start)
        peaks: dict[int, int] = {}
        for (sec, _), n in per_client.items():
            peaks[sec] = max(peaks.get(sec, 0), n)
        for sec, n in peaks.items():
            run.add("peak", sec, n / lab.CLIENT_RATE)

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def warnings(self, run: Run, inc: Incident):
        for s in range(int(inc.t0), int(inc.t1) + 1):
            if run.series("failed_s", s, s + 1)[0]:
                return [(s + 1.0, self.s("warn_503"))]
        return []

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s("calm_again")
        n = int(inc.severity)
        who = self.s("who_one") if n == 1 else self.s("who_many", n=n)
        return self.s("flooded", who=who, cause=self.cause(inc))

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def backend_at(self, run: Run, t: float) -> int:
        """Requests at the backend (working or waiting) at time t."""
        return sum(1 for r in run.active("requests", t, REQ_END) if r[REQ_OUTCOME] != LIMITED)

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        last = run.rows("requests", t - 1, t)
        sent = sum(1 for r in last if r[REQ_OUTCOME] != LIMITED)
        failing = any(r[REQ_OUTCOME] == FAILED for r in run.rows("requests", t - 2, t))

        def load_state(v: float, failed: bool) -> str:
            return "bad" if failed else "warn" if v > 0.9 * lab.CAPACITY else "ok"

        def load_s(s: int):
            v = run.series("sent", s, s + 1)[0]
            return v, load_state(v, bool(run.series("failed_s", s, s + 1)[0]))

        recent = [r for r in run.rows("requests", t - 5 - run.max_dur.get("requests", 0), t)
                  if not r[REQ_FLOOD] and t - 5 <= r[REQ_END] < t]
        others = _served(recent)
        others = 1.0 if others is None else others

        def others_state(v: float) -> str:
            return "bad" if v < lab.OTHERS_MIN else "ok"

        def others_s(s: int):
            n, ok = run.series("others", s, s + 1)[0], run.series("others_ok", s, s + 1)[0]
            v = ok / n if n else 1.0
            return v, others_state(v)

        peak = _peak(last)

        def peak_state(v: float) -> str:
            return "bad" if v > lab.PEAK_MAX else "warn" if v > 1.2 else "ok"

        def peak_s(s: int):
            v = run.series("peak", s, s + 1)[0]
            return v, peak_state(v)

        tiles = [
            Tile(self.s("tile_load"), f"{sent}/s", f"≤{lab.CAPACITY:.0f}", load_state(sent, failing),
                 history(run, t, load_s)),
            Tile(self.s("tile_others"), f"{others:.0%}", "≥99%", others_state(others),
                 history(run, t, others_s)),
            Tile(self.s("tile_peak"), f"{peak:.1f}x", "≤1.6x", peak_state(peak), history(run, t, peak_s)),
        ]
        ask_n = sum(1 for r in last if not r[REQ_FLOOD])
        ask_f = len(last) - ask_n
        ok_n = sum(1 for r in last if not r[REQ_FLOOD] and r[REQ_OUTCOME] == SERVED)
        ok_f = sum(1 for r in last if r[REQ_FLOOD] and r[REQ_OUTCOME] == SERVED)
        bad = sum(1 for r in last if r[REQ_OUTCOME] == FAILED)
        bars = [
            Bar(self.s("bar_clients"), [(ask_n, WHITE), (ask_f, EXTRA2)]),
            Bar(self.s("bar_backend"), [(ok_n, WHITE), (ok_f, EXTRA2), (bad, RED)]),
        ]
        headline, colour = self._headline(variant, t, sent)
        return Traffic(tiles, bars, lab.CAPACITY, self.s("limit", limit=lab.CAPACITY), headline, colour,
                       title=self.s("requests"), top=450.0)

    def _headline(self, variant: str, t: float, sent: int):
        inc = self.incident_at(variant, t)
        if inc is not None:
            colour = RED if sent > lab.CAPACITY else BLUE
            return self.s("head_flood", n=int(inc.severity), sent=sent), colour
        return self.s("head_calm", sent=sent, capacity=lab.CAPACITY), MUTED

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        s = int(t)
        span = run.max_dur.get("requests", 0.0)
        partial = [r for r in run.rows("requests", s - span - 1, t) if s <= r[REQ_END] < t]
        served = run.total("served", t) + sum(1 for r in partial if r[REQ_OUTCOME] == SERVED)
        limited = run.total("limited", t) + sum(1 for r in partial if r[REQ_OUTCOME] == LIMITED)
        failed = run.total("failed", t) + sum(1 for r in partial if r[REQ_OUTCOME] == FAILED)
        waiting = self.backend_at(run, t)
        waits = [r[REQ_END] - r[REQ_START] for r in run.rows("requests", t - 5 - span, t)
                 if t - 5 <= r[REQ_END] < t and r[REQ_OUTCOME] == SERVED]
        words = self.screen.STATS
        return [
            (words["served"], fmt_int(served), GREEN),
            (self.s("stat_limited"), fmt_int(limited), EXTRA3 if limited else MUTED),
            (words["failed"], fmt_int(failed), RED if failed else MUTED),
            (words["waiting"], fmt_int(waiting), EXTRA2 if waiting > 15 else WHITE),
            (words["p50"], fmt_ms(percentile(waits, 50)), WHITE),
            (words["p99"], fmt_ms(percentile(waits, 99)), WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("ok_normal", [])), (EXTRA2, run.hist.get("ok_flood", [])),
                (RED, run.hist.get("failed_s", []))]

    def chart_limit(self):
        return lab.CAPACITY, f"{lab.CAPACITY:.0f}/s"

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = RateLimitWorld
