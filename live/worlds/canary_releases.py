"""World for lab canary_releases. Its words are in labs/canary_releases/text/<lang>.py."""

from __future__ import annotations

import math

from core.i18n import lab_text
from labs.canary_releases import lab
from labs.canary_releases.scenario import (
    CANCEL,
    DEPLOY,
    FIRST_VERSION,
    FULL,
    MANUAL,
    ROLLBACK,
    SLOW,
    STEP,
    bad,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, ORANGE, PURPLE, RED, RGB, WHITE
from live.worlds.base import (
    Bar,
    GoalSpec,
    Incident,
    Run,
    Settled,
    Table,
    Tile,
    TimelineEvent,
    Traffic,
    World,
    _event_order,
    fmt_ms,
    history,
    percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_CANARY, REQ_EP, REQ_HARMED, REQ_SLOW = range(8)
T_T, T_REL, T_BEFORE, T_AFTER, T_CN, T_CERR, T_CSLOW, T_BN, T_BERR, T_BSLOW = range(10)
E_T, E_REL, E_VERSION, E_WHAT, E_WEIGHT, E_LIVE = range(6)
INCIDENT_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
LIVE_C, CANARY_C, SLOW_C, FAILED_C = BLUE, PURPLE, EXTRA2, RED  # the builds and the answers, in every picture
ROLLED_BACK = 15.0  # seconds a rollback stays in the headline
ERRORS_MAX = 0.01  # the Errors tile turns red above this


def version_of(inc: Incident) -> int:
    """The build release `inc` ships."""
    return FIRST_VERSION + 1 + inc.index


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Requests that ended in [a, b)."""
    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b]


def events(run: Run, release: int | None = None, upto: float = math.inf) -> list[tuple]:
    """What the router did (kept for the whole run): of one release, at or before `upto`."""
    return [e for e in run.data.get("events", ()) if e[E_T] <= upto and (release is None or e[E_REL] == release)]


def router(run: Run, t: float) -> tuple[int, int | None, float, tuple | None]:
    """(live version, version being released or None, its share of the traffic, the last event) at t."""
    seen = events(run, upto=t)
    if not seen:
        return FIRST_VERSION, None, 0.0, None
    last = seen[-1]
    if last[E_WHAT] in (DEPLOY, STEP):
        return last[E_LIVE], last[E_VERSION], last[E_WEIGHT], last
    return last[E_LIVE], None, 0.0, last


def _memo(measure):
    """A frame asks for the same goal values several times: remember the last few, in the run itself (a run
    only grows, so its piece count tells an old answer from a new one)."""

    def cached(run: Run, inc: Incident, upto: float):
        cache = run.data.setdefault(f"memo_{measure.__name__}", {})
        key = (run.pieces, inc.index, upto)
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[key] = measure(run, inc, upto)
        return cache[key]

    return cached


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _baseline(run: Run, inc: Incident, upto: float):
    """Errors of the requests answered in the BASELINE_WINDOW s before the deploy."""
    a, b = _before(inc)
    rows = _ended(run, a, min(b, upto))
    if not rows:
        return None, "–"
    v = sum(not r[REQ_OK] for r in rows) / len(rows)
    return v, f"{v:.1%}"


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


@_memo
def _hurt(run: Run, inc: Incident, upto: float):
    """Requests the new build hurt (failed or slowed by it) / every request of the release window."""
    end = min(inc.t1, upto)
    rows = [r for r in run.rows("requests", inc.t0, end) if r[REQ_END] <= upto]
    if not rows or end <= inc.t0:
        return None, "–"
    # While the window is open: the hurt so far over the requests the whole window will have (as many per
    # second as so far), so the value only grows, and is exact once the window closes.
    v = sum(r[REQ_HARMED] for r in rows) / (len(rows) * (inc.t1 - inc.t0) / (end - inc.t0))
    return v, f"{v:.2%}"


def _hurt_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _hurt(run, inc, upto)
    return v is not None and v > lab.HURT_MAX


def _outcome(run: Run, inc: Incident, upto: float) -> tuple | None:
    """How the release ended (full, rollback or cancel), if it has by `upto`."""
    return next((e for e in events(run, inc.index, upto) if e[E_WHAT] in (FULL, ROLLBACK, CANCEL)), None)


def _full(run: Run, inc: Incident, upto: float):
    """1 when a bad build reached 100% of the traffic."""
    if upto <= inc.t0:
        return None, "–"
    end = _outcome(run, inc, upto)
    v = int(bad(inc.kind) and end is not None and end[E_WHAT] == FULL)
    return float(v), str(v)


def _full_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _full(run, inc, upto)
    return bool(v)


def _alarms(run: Run, inc: Incident, upto: float):
    """1 when a good build was rolled back by the controller (a false alarm)."""
    if upto <= inc.t0:
        return None, "–"
    end = _outcome(run, inc, upto)
    v = int(not bad(inc.kind) and end is not None and end[E_WHAT] == ROLLBACK)
    return float(v), str(v)


def _alarms_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _alarms(run, inc, upto)
    return bool(v)


def _rollout(run: Run, inc: Incident, upto: float):
    """Seconds from the deploy to 100% for a good build (a bad one: nothing to time)."""
    if upto <= inc.t0:
        return None, "–"
    if bad(inc.kind):
        return 0.0, "–"
    end = _outcome(run, inc, upto)
    if end is None:  # still ramping
        took = min(upto, inc.t1) - inc.t0
        return took, f"{took:.0f}s"
    if end[E_WHAT] != FULL:
        return math.inf, lab_text("canary_releases").STRINGS["never"]
    took = end[E_T] - inc.t0
    return took, f"{took:.0f}s"


def _rollout_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _rollout(run, inc, upto)
    return v is not None and v > lab.ROLLOUT_MAX


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v <= lab.BASELINE_MAX, key="baseline"),
    GoalSpec("", "during", "", _during, _hurt,
             lambda v: v is not None and v <= lab.HURT_MAX, doomed=_hurt_doomed, settle_extra=lab.SETTLE,
             key="hurt"),
    GoalSpec("", "during", "", _during, _full,
             lambda v: v is not None and v <= lab.FULL_MAX, doomed=_full_doomed, key="full"),
    GoalSpec("", "after", "", _during, _alarms,
             lambda v: v is not None and v <= lab.ALARMS_MAX, doomed=_alarms_doomed, key="alarms"),
    GoalSpec("", "after", "", _during, _rollout,
             lambda v: v is not None and v <= lab.ROLLOUT_MAX, doomed=_rollout_doomed, key="rollout"),
]

# How each router event shows in the timeline: (VERBS key, STRINGS key, colour, kind).
EVENTS = {
    STEP: ("step", "ev_step", PURPLE, ""),
    CANCEL: ("cancel", "ev_cancel", ORANGE, "warn"),
    MANUAL: ("manual", "ev_manual", ORANGE, "warn"),
}


class CanaryReleasesWorld(World):
    id = "canary_releases"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "request"), ([EXTRA1, EXTRA2, EXTRA3], "waits", "●"),
              (GREEN, "served"), (FAILED_C, "failed"), (LIVE_C, "live", "◉"), (CANARY_C, "canary", "◉"),
              (SLOW_C, "slow", "█"), (INCIDENT_KEY, "incident", "█")]
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "ticks": Table(sort=T_T, times=(T_T,)),
        "events": Table(sort=E_T, times=(E_T,)),
    }
    goals = GOALS
    incident_verbs = ("deploy", "close")

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.rate = float(self.params.get("rate", 200.0))
        self.chart_top = self.rate * 1.3

    # ---------------------------------------------------------------- incidents

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(inc.kind), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        v = version_of(inc)
        if not start:
            return self.s("release_end", v=v)
        key = "bad_start" if bad(inc.kind) else f"{inc.kind}_start"  # good_start, flaky_start
        return self.s(key, v=v, cause=self.cause(inc))

    def release_at(self, run: Run, t: float) -> Incident | None:
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            s = r[REQ_START]
            run.add("ask", s)
            run.add("served" if r[REQ_OK] else "failed", r[REQ_END])
            if r[REQ_HARMED]:
                run.add("hurt", s)
            if r[REQ_CANARY]:
                run.add("canary", s)
            run.add("c_failed" if not r[REQ_OK] else "c_slow" if r[REQ_SLOW] else
                    "c_canary" if r[REQ_CANARY] else "c_live", s)
        stored = run.data.setdefault("events", [])
        for e in tables["events"]:
            stored.append(e)
            ev = self._event(run, e)
            if ev is not None:
                run.timeline.append(ev)
            if e[E_WHAT] == STEP and 0.0 < e[E_WEIGHT] < 1.0:
                run.data.setdefault("split", set()).add(e[E_REL])
        run.timeline.sort(key=_event_order)

    def _event(self, run: Run, e: tuple) -> TimelineEvent | None:
        """A router event in the timeline, a hair after the deploy or the window's end it may share a time
        with, so it shows as the newer one."""
        what, k = e[E_WHAT], e[E_REL]
        e = (e[E_T] + 0.01, *e[1:])
        inc = run.incidents[k] if k < len(run.incidents) else None
        is_bad = inc is not None and bad(inc.kind)
        values = {"v": e[E_VERSION], "w": e[E_WEIGHT], "live": e[E_LIVE]}
        if what == FULL:
            if is_bad:
                return TimelineEvent(e[E_T], self.word("full"), self.s("ev_full_bad", **values), RED, k, kind="warn")
            return TimelineEvent(e[E_T], self.word("full"), self.s("ev_full", **values), BLUE, k)
        if what == ROLLBACK:
            if is_bad:
                return TimelineEvent(e[E_T], self.word("rollback"), self.s("ev_caught", **values), GREEN, k)
            return TimelineEvent(e[E_T], self.word("rollback"), self.s("ev_false", **values), ORANGE, k, kind="warn")
        spec = EVENTS.get(what)
        if spec is None:
            return None
        verb, key, colour, kind = spec
        return TimelineEvent(e[E_T], self.word(verb), self.s(key, **values), colour, k, kind=kind)

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(0 in run.data.get("split", ()), *(r.ok for r in first))

    # ---------------------------------------------------------------- panel

    def _share(self, run: Run, a: int, b: int, top: str, bottom: str = "ask") -> float | None:
        x, y = sum(run.series(top, a, b)), sum(run.series(bottom, a, b))
        return x / y if y else None

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        s = int(t)

        def hurt_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.HURT_MAX else "warn" if v > 0 else "ok"

        def hurt_s(sec: int):
            v = self._share(run, sec, sec + 1, "hurt")
            return (v or 0.0), hurt_state(v)

        hurt = self._share(run, s - 60, s, "hurt")

        def err_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > ERRORS_MAX else "warn" if v > ERRORS_MAX / 2 else "ok"

        def err_s(sec: int):
            v = self._share(run, sec, sec + 1, "failed", "ask")
            return (v or 0.0), err_state(v)

        errors = self._share(run, s - 5, s, "failed")

        def p99_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= SLOW else "warn" if v >= SLOW * 0.8 else "ok"

        def p99_s(sec: int):
            v = percentile([r[REQ_END] - r[REQ_START] for r in _ended(run, sec, sec + 1)], 99)
            return (v or 0.0), p99_state(v)

        p99 = percentile([r[REQ_END] - r[REQ_START] for r in _ended(run, t - 5, t)], 99)
        tiles = [
            Tile(self.s("tile_hurt"), "–" if hurt is None else f"{hurt:.2%}", f"≤{lab.HURT_MAX:.1%}",
                 hurt_state(hurt), history(run, t, hurt_s)),
            Tile(self.s("tile_errors"), "–" if errors is None else f"{errors:.1%}", f"≤{ERRORS_MAX:.0%}",
                 err_state(errors), history(run, t, err_s)),
            Tile(self.screen.STATS["p99"], fmt_ms(p99), f"<{fmt_ms(SLOW)}", p99_state(p99), history(run, t, p99_s)),
        ]

        live, new, weight, _ = router(run, t)
        asked = run.series("ask", s - 1, s)[0]
        canary = run.series("canary", s - 1, s)[0]
        hurt_now = run.series("hurt", s - 1, s)[0]
        bars = [
            Bar(self.s("bar_live", v=live), [(asked - canary, LIVE_C)]),
            Bar(self.s("bar_new", v=new) if new is not None else self.s("bar_none"), [(canary, CANARY_C)]),
            Bar(self.s("bar_hurt"), [(hurt_now, FAILED_C)]),
        ]
        headline, colour = self._headline(run, t, live, new, weight)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("toplist"),
                       subtitle=self.s("toplist_sub"), top=self.rate * 1.3)

    def _headline(self, run: Run, t: float, live: int, new: int | None, weight: float) -> tuple[str, RGB]:
        inc = self.release_at(run, t)
        if inc is not None and bad(inc.kind) and live == version_of(inc):
            return self.s("head_bad_live", v=live), RED
        if new is not None:
            ticks = [r for r in run.rows("ticks", t - 6.0, t + 1e-9) if r[T_REL] == inc.index] if inc else []
            if not ticks or not ticks[-1][T_CN] or not ticks[-1][T_BN]:
                return self.s("head_canary", v=new, w=weight), CANARY_C
            r = ticks[-1]
            return self.s("head_compare", v=new, w=weight, ce=r[T_CERR] / r[T_CN], be=r[T_BERR] / r[T_BN],
                          cs=r[T_CSLOW] / r[T_CN], bs=r[T_BSLOW] / r[T_BN]), CANARY_C
        back = [e for e in events(run, upto=t) if e[E_WHAT] == ROLLBACK and e[E_T] > t - ROLLED_BACK]
        if back:
            return self.s("head_rolled_back", v=back[-1][E_VERSION], live=live), GREEN
        s = int(t)
        errors = self._share(run, s - 5, s, "failed")
        if errors is not None and errors > ERRORS_MAX:
            return self.s("head_errors", e=errors), ORANGE
        return self.s("head_live", v=live), BLUE

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "requests", REQ_START, REQ_END, REQ_OK, t, busy=40)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(LIVE_C, run.hist.get("c_live", [])), (CANARY_C, run.hist.get("c_canary", [])),
                (SLOW_C, run.hist.get("c_slow", [])), (FAILED_C, run.hist.get("c_failed", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = CanaryReleasesWorld
