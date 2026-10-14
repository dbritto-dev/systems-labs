"""World for lab webhook_delivery. Its words are in labs/webhook_delivery/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.webhook_delivery import lab
from labs.webhook_delivery.api import CLIENT_TIMEOUT, WORKERS
from labs.webhook_delivery.scenario import ENDPOINT_KINDS, endpoint_of
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, PURPLE, RED, WHITE,
)
from live.worlds.base import (
    KEEP, PIECE, Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, fmt_int, fmt_ms, history,
    percentile,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
INF = float("inf")

EV_CREATED, EV_ID, EV_ENDPOINT, EV_KEY, EV_SEQ, EV_POISON = range(6)
AT_START, AT_ID, AT_ENDPOINT, AT_END, AT_STATUS, AT_OK, AT_N, AT_WORKER = range(8)
DL_T, DL_ID, DL_ENDPOINT, DL_CREATED, DL_OOO, DL_N = range(6)
GU_T, GU_ID, GU_ENDPOINT, GU_CREATED, GU_POISON = range(5)
SM_T, SM_BUSY, SM_PENDING, SM_PER = range(4)

_s = strings("webhook_delivery")  # one of the lab's STRINGS, for the goal measures below


def sick(inc: Incident | None) -> int:
    """The endpoint an incident hits, or -1 (a burst hits no one in particular)."""
    if inc is None or inc.kind not in ENDPOINT_KINDS:
        return -1
    return endpoint_of(inc.severity)


def attempt_colour(n: int):
    """An attempt's colour: white the first, light then mid orange for retries."""
    return WHITE if n <= 1 else EXTRA1 if n == 2 else EXTRA2


def delivered_at(run: Run, eid: int) -> float:
    """When an event was delivered (inf: not as far as the run has got)."""
    return run.data["dt"].get(eid, INF)


def gave_up_at(run: Run, eid: int) -> float:
    return run.data["gu"].get(eid, INF)


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _made(run: Run, inc: Incident, upto: float, window=_window) -> list[tuple]:
    """Events made in the window by `upto` (malformed ones aside: they can never be delivered)."""
    a, b = window(inc)
    return [e for e in run.rows("events", a, min(b, upto)) if not e[EV_POISON]]


def _baseline(run: Run, inc: Incident, upto: float):
    upto = min(upto, inc.t0 + 5.0)
    made = _made(run, inc, upto, _before)
    if not made:
        return None, "–"
    v = sum(1 for e in made if delivered_at(run, e[EV_ID]) <= upto) / len(made)
    return v, f"{v:.0%}"


def _lost_count(run: Run, inc: Incident, upto: float) -> int:
    deadline = _window(inc)[1] + lab.SETTLE
    upto = min(upto, deadline)
    n = 0
    for e in _made(run, inc, upto):
        if gave_up_at(run, e[EV_ID]) <= upto:
            n += 1
        elif upto >= deadline and delivered_at(run, e[EV_ID]) > deadline:
            n += 1  # never delivered, and never given up either: silently dropped, or stuck
    return n


def _lost(run: Run, inc: Incident, upto: float):
    if not _made(run, inc, upto):
        return None, "–"
    n = _lost_count(run, inc, upto)
    return n, fmt_int(n)


def _ooo_count(run: Run, inc: Incident, upto: float) -> int:
    a, b = _window(inc)
    upto = min(upto, b + lab.SETTLE)
    return sum(1 for d in run.rows("delivered", a, upto) if d[DL_OOO] and a <= d[DL_CREATED] < b)


def _order(run: Run, inc: Incident, upto: float):
    if not _made(run, inc, upto):
        return None, "–"
    n = _ooo_count(run, inc, upto)
    return n, fmt_int(n)


def _waits(run: Run, inc: Incident, upto: float) -> list[float]:
    """Seconds from made to delivered for the healthy endpoints' events (still waiting: so far)."""
    upto = min(upto, _window(inc)[1] + lab.P99_SETTLE)
    bad = sick(inc)
    return [min(delivered_at(run, e[EV_ID]), upto) - e[EV_CREATED] for e in _made(run, inc, upto)
            if e[EV_ENDPOINT] != bad]


def _p99(run: Run, inc: Incident, upto: float):
    v = percentile(_waits(run, inc, upto), 99)
    if v is None:
        return None, "–"
    return v, fmt_ms(v)


def _doomed_p99(run: Run, inc: Incident, upto: float) -> bool:
    a, b = _window(inc)
    total = sum(1 for e in run.rows("events", a, b) if e[EV_ENDPOINT] != sick(inc) and not e[EV_POISON])
    late = sum(1 for w in _waits(run, inc, upto) if w >= lab.P99_MAX)
    return total > 0 and late > total * 0.01  # more than 1% already waited too long: the p99 cannot pass


def _wasted(run: Run, inc: Incident, upto: float) -> float:
    """Worker-seconds spent in the window on attempts that failed (and had ended by `upto`)."""
    a, b = _window(inc)
    hi = min(b, upto)
    total = 0.0
    for r in run.rows("attempts", a - CLIENT_TIMEOUT, hi):
        if not r[AT_OK] and r[AT_END] <= upto:
            total += max(0.0, min(r[AT_END], hi) - max(r[AT_START], a))
    return total


def _waste(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    if upto <= a:
        return None, "–"
    v = _wasted(run, inc, upto) / (WORKERS * (b - a))
    return v, f"{v:.0%}"


def _doomed_waste(run: Run, inc: Incident, upto: float) -> bool:
    a, b = _window(inc)
    return _wasted(run, inc, upto) > lab.WASTE_MAX * WORKERS * (b - a)


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v >= lab.BASELINE_MIN, settle_extra=5.0, key="baseline"),
    GoalSpec("", "after", "", _window, _lost, lambda v: v == 0,
             doomed=lambda run, inc, upto: _lost_count(run, inc, upto) > 0, settle_extra=lab.SETTLE, key="lost"),
    GoalSpec("", "after", "", _window, _order, lambda v: v == 0,
             doomed=lambda run, inc, upto: _ooo_count(run, inc, upto) > 0, settle_extra=lab.SETTLE, key="order"),
    GoalSpec("", "during", "", _window, _p99, lambda v: v is not None and v < lab.P99_MAX,
             doomed=_doomed_p99, settle_extra=lab.P99_SETTLE, key="p99"),
    GoalSpec("", "during", "", _window, _waste, lambda v: v is not None and v <= lab.WASTE_MAX,
             doomed=_doomed_waste, settle_extra=1.0, key="waste"),
]


class WebhookWorld(World):
    id = "webhook_delivery"
    view = "cluster"  # which endpoint is dead, and which workers are stuck on it, shows best as nodes
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first"), ([EXTRA1, EXTRA2], "retry"), (GREEN, "delivered"),
              (EXTRA3, "out_of_order"), (RED, "failed"), (PURPLE, "gave_up"), (LIMIT, "limit", "┄"),
              (DOWN_KEY, "incident", "█")]
    tables = {
        "events": Table(sort=EV_CREATED, times=(EV_CREATED,)),
        "attempts": Table(sort=AT_START, times=(AT_START, AT_END)),
        "delivered": Table(sort=DL_T, times=(DL_T,)),
        "gaveup": Table(sort=GU_T, times=(GU_T,)),
        "samples": Table(sort=SM_T, times=(SM_T,)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 60.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        dt = run.data.setdefault("dt", {})  # event id -> delivered at
        gu = run.data.setdefault("gu", {})  # event id -> given up at
        made = run.data.setdefault("made", {})  # event id -> made at (to forget old ids)
        for e in tables["events"]:
            run.add("made", e[EV_CREATED])
            made[e[EV_ID]] = e[EV_CREATED]
        for r in tables["attempts"]:
            if r[AT_OK]:
                run.add("ok_first" if r[AT_N] <= 1 else "ok_retry", r[AT_START])
            else:
                run.add("failed", r[AT_START])
        for d in tables["delivered"]:
            dt[d[DL_ID]] = d[DL_T]
            run.add("served", d[DL_T])
            if d[DL_OOO]:
                run.add("ooo", d[DL_T])
            if d[DL_ENDPOINT] != sick(self.incident_at(run, d[DL_T])):
                run.add("healthy", d[DL_T])
                if d[DL_T] - d[DL_CREATED] >= lab.P99_MAX:
                    run.add("late", d[DL_T])
        for g in tables["gaveup"]:
            gu[g[GU_ID]] = g[GU_T]
            run.add("gaveup", g[GU_T])
            if not g[GU_POISON]:
                run.add("lost", g[GU_T])
        cutoff = run.end - KEEP - 3 * PIECE  # forget ids made long ago (raw rows are gone too)
        if len(made) > 40_000:
            old = [i for i, c in made.items() if c < cutoff]
            for i in old:
                del made[i]
                dt.pop(i, None)
                gu.pop(i, None)

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "back" if sick(inc) >= 0 else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end", n=sick(inc) + 1)
        return self.s(f"{inc.kind}_start", n=sick(inc) + 1, times=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        out = []
        a, b = _window(inc)
        lost = sum(1 for g in run.rows("gaveup", a, inc.t1) if not g[GU_POISON])
        if lost:
            out.append((inc.t1, self.s("warn_lost", n=lost)))
        stuck = self.stuck_on(run, inc.t0 + min(5.0, (inc.t1 - inc.t0) / 2), sick(inc))
        if stuck >= WORKERS // 2:
            out.append((inc.t0 + min(5.0, (inc.t1 - inc.t0) / 2), self.s("warn_stuck", n=stuck, of=WORKERS)))
        return out

    def incident_at(self, run: Run, t: float) -> Incident | None:
        return next((i for i in reversed(run.incidents) if i.t0 <= t < max(i.t1, i.t0 + 1.0)), None)

    # ---------------------------------------------------------------- the workers at t

    def sample_at(self, run: Run, t: float) -> tuple | None:
        rows = run.rows("samples", t - 1.0, t + 1e-9)
        return rows[-1] if rows else None

    def in_flight(self, run: Run, t: float) -> list[tuple]:
        """Attempts in flight at t."""
        return run.active("attempts", t, AT_END)

    def stuck_on(self, run: Run, t: float, endpoint: int) -> int:
        """Workers busy with one endpoint at t."""
        if endpoint < 0:
            return 0
        return sum(1 for r in self.in_flight(run, t) if r[AT_ENDPOINT] == endpoint)

    def pending_events(self, run: Run, t: float, back: float = 60.0) -> list[tuple]:
        """Events made in the last `back` seconds and neither delivered nor given up by t."""
        dt, gu = run.data.get("dt", {}), run.data.get("gu", {})
        return [e for e in run.rows("events", t - back, t + 1e-9)
                if dt.get(e[EV_ID], INF) > t and gu.get(e[EV_ID], INF) > t]

    def ended(self, run: Run, t: float, back: float) -> list[tuple]:
        """Attempts that ended in the last `back` seconds."""
        span = run.max_dur.get("attempts", 0.0)
        return [r for r in run.rows("attempts", t - back - span, t + 1e-9) if t - back <= r[AT_END] <= t]

    def state(self, run: Run, variant: str, t: float):
        """The word under the picture, and its colour."""
        inc = self.incident_at(run, t)
        bad = sick(inc)
        if inc is None:
            return self.screen.STATES["healthy"], GREEN
        word = self.s(f"state_{inc.kind}", n=bad + 1)
        colour = RED if inc.kind in ("down", "hang") else EXTRA2 if inc.kind in ("slow", "burst") else PURPLE
        return word, colour

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        lost = int(sum(run.series("lost", int(t) - 10, int(t))))
        ooo = int(sum(run.series("ooo", int(t) - 10, int(t))))

        def lost_s(s: int):
            v = run.series("lost", s, s + 1)[0]
            return v, "bad" if v else "ok"

        def ooo_s(s: int):
            v = run.series("ooo", s, s + 1)[0]
            return v, "bad" if v else "ok"

        inc = self.incident_at(run, t)
        bad = sick(inc)
        span = run.max_dur.get("delivered", 0.0)
        waits = [d[DL_T] - d[DL_CREATED] for d in run.rows("delivered", t - 10 - span, t + 1e-9)
                 if d[DL_ENDPOINT] != bad]
        p99 = percentile(waits, 99)

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.P99_MAX else "warn" if v >= lab.P99_MAX / 2 else "ok"

        def late_s(s: int):
            n, late = run.series("healthy", s, s + 1)[0], run.series("late", s, s + 1)[0]
            v = late / n if n else 0.0
            return v, "bad" if v > 0.01 else "warn" if v else "ok"

        tiles = [
            Tile(self.s("tile_lost"), fmt_int(lost), "=0", "bad" if lost else "ok", history(run, t, lost_s)),
            Tile(self.s("tile_order"), fmt_int(ooo), "=0", "bad" if ooo else "ok", history(run, t, ooo_s)),
            Tile(self.s("tile_p99"), fmt_ms(p99), "<1s", p99_state(p99), history(run, t, late_s)),
        ]
        made = run.count("events", t - 1, t)
        started = run.rows("attempts", t - 1, t)
        first = sum(1 for r in started if r[AT_N] <= 1)
        out = self.ended(run, t, 1.0)
        good = sum(1 for r in out if r[AT_OK])
        gave = run.count("gaveup", t - 1, t)
        bars = [
            Bar(self.s("bar_made"), [(float(made), WHITE)]),
            Bar(self.s("bar_sent"), [(float(first), WHITE), (float(len(started) - first), EXTRA2)]),
            Bar(self.s("bar_ended"), [(float(good), GREEN), (float(len(out) - good), RED), (float(gave), PURPLE)]),
        ]
        stuck = self.stuck_on(run, t, bad)
        if lost:
            headline, colour = self.s("head_lost", n=lost), PURPLE
        elif stuck >= WORKERS // 2:
            headline, colour = self.s("head_stuck", n=stuck, of=WORKERS, endpoint=bad + 1), RED
        elif ooo:
            headline, colour = self.s("head_order", n=ooo), EXTRA3
        elif inc is not None:
            headline, colour = self.s(f"head_{inc.kind}", n=bad + 1), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=self.rate * 3)

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        sample = self.sample_at(run, t)
        pending = sample[SM_PENDING] if sample else 0
        lost = run.total("lost", t)
        ooo = run.total("ooo", t)
        return [
            (self.s("stat_delivered"), fmt_int(run.total("served", t)), GREEN),
            (self.s("stat_lost"), fmt_int(lost), PURPLE if lost else MUTED),
            (self.s("stat_pending"), fmt_int(pending), EXTRA2 if pending > self.rate * 2 else WHITE),
            (self.s("stat_order"), fmt_int(ooo), EXTRA3 if ooo else MUTED),
            (self.s("stat_busy"), f"{sample[SM_BUSY] if sample else 0}/{WORKERS}", WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("ok_first", [])), (EXTRA2, run.hist.get("ok_retry", [])),
                (RED, run.hist.get("failed", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    chart_top = 150.0

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = WebhookWorld
