"""World for lab graceful_shutdown. Its words are in labs/graceful_shutdown/text/<lang>.py."""

from __future__ import annotations

from labs.graceful_shutdown import lab
from labs.graceful_shutdown.scenario import (
    CUT, DRAINING, GONE, INSTANCES, LEAVING, REFUSING, SAMPLE, SERVING, STARTING,
)
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, PURPLE, RED, RGB, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history,
)

REQ_ID, REQ_START, REQ_END, REQ_OK, REQ_OUT, REQ_SLOT, REQ_LB, REQ_KEPT, REQ_OLD = range(9)
ST_END, ST_START, ST_SLOT, ST_OUT, ST_LB, ST_ID = range(6)
IN_SIGTERM, IN_EXIT, IN_SLOT, IN_KILLED, IN_CUT, IN_ID = range(6)
S_T, S_STATES, S_SERVING, S_FLYING = range(4)
HIT_T0, HIT_T1, HIT_SLOT = range(3)
INCIDENT_KEY: RGB = (110, 44, 56)  # the legend swatch for the shaded incidents
EDGE = 0.05  # seconds: the virtual clock lands a hair before an incident's planned start
WARN_FAILED = 5  # failed requests in one second that make a warning
STATE_COLOURS = {GONE: DIM, STARTING: PURPLE, SERVING: BLUE, LEAVING: EXTRA2, DRAINING: EXTRA2, REFUSING: RED}


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Requests that ended in [a, b)."""
    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b]


def _share(rows: list[tuple]) -> float | None:
    return sum(not r[REQ_OK] for r in rows) / len(rows) if rows else None


def _pct(v: float) -> str:
    return f"{v:.2%}" if v < 0.1 else f"{v:.0%}"


def _stopped(run: Run, inc: Incident, upto: float) -> list[tuple]:
    """Instances that got SIGTERM in this incident and were gone by `upto`."""
    return [r for r in run.rows("instances", inc.t0 - EDGE, inc.t1) if r[IN_EXIT] <= upto]


# ---------------------------------------------------------------- goals


def _before(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BASELINE_WINDOW, inc.t0


def _baseline(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    v = _share(_ended(run, a, min(b - EDGE, upto)))  # a request cut by the first SIGTERM is not the baseline
    return (None, "–") if v is None else (v, _pct(v))


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _errors(run: Run, inc: Incident, upto: float):
    """The share of the requests started during the incident that failed (refused, or cut)."""
    rows = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_END] <= upto]
    v = _share(rows)
    return (None, "–") if v is None else (v, _pct(v))


def _errors_doomed(run: Run, inc: Incident, upto: float) -> bool:
    """More requests have failed than 0.1% of everything the incident can still see."""
    failed = sum(not r[REQ_OK] for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_END] <= upto)
    rate = float(run.data.get("rate", 300.0))
    return failed > lab.ERRORS_MAX * rate * 1.3 * (inc.t1 - inc.t0)


def _cut(run: Run, inc: Incident, upto: float):
    """Requests and streams cut mid-flight by the instances this incident stopped."""
    rows = _stopped(run, inc, upto)
    if not rows and upto < inc.t0 + 0.5:
        return None, "–"
    v = sum(r[IN_CUT] for r in rows)
    return v, f"{v:,}"


def _cut_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return any(r[IN_CUT] for r in _stopped(run, inc, upto))


def _capacity(run: Run, inc: Incident, upto: float):
    """The fewest instances serving (in the balancer and accepting) at any moment of the incident."""
    rows = run.rows("samples", inc.t0, min(inc.t1, upto))
    if not rows:
        return None, "–"
    v = min(r[S_SERVING] for r in rows)
    return v, f"{v}/{INSTANCES}"


def _capacity_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _capacity(run, inc, upto)
    return v is not None and v < lab.CAPACITY_MIN


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.KILL_WAIT - 1.0


def _exited(run: Run, inc: Incident, upto: float):
    """The longest shutdown (SIGTERM to exit) of this incident's instances; killed ones fail."""
    rows = _stopped(run, inc, upto)
    if not rows:
        return None, "–"
    killed = sum(r[IN_KILLED] for r in rows)
    longest = max(r[IN_EXIT] - r[IN_SIGTERM] for r in rows)
    if killed:
        return -killed, "SIGKILL ×" + str(killed)
    return longest, f"{longest:.1f}s"


def _exited_doomed(run: Run, inc: Incident, upto: float) -> bool:
    return any(r[IN_KILLED] for r in _stopped(run, inc, upto))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline,
             lambda v: v is not None and v <= lab.ERRORS_MAX, key="baseline"),
    GoalSpec("", "during", "", _during, _errors,
             lambda v: v is not None and v <= lab.ERRORS_MAX, doomed=_errors_doomed, settle_extra=lab.SETTLE,
             key="errors"),
    GoalSpec("", "during", "", _during, _cut,
             lambda v: v is not None and v <= lab.CUT_MAX, doomed=_cut_doomed, settle_extra=lab.KILL_WAIT,
             key="cut"),
    GoalSpec("", "during", "", _during, _capacity,
             lambda v: v is not None and v >= lab.CAPACITY_MIN, doomed=_capacity_doomed, key="capacity"),
    GoalSpec("", "after", "", _after, _exited,
             lambda v: v is not None and v >= 0, doomed=_exited_doomed, settle_extra=1.0, key="exited"),
]


class GracefulShutdownWorld(World):
    id = "graceful_shutdown"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "request"), ([EXTRA1, EXTRA2, EXTRA3], "waits", "●"),
              (GREEN, "served"), (RED, "failed"), (BLUE, "serving", "◉"), (PURPLE, "starting", "◉"),
              (EXTRA2, "draining", "◉"), (DIM, "terminated", "◉"), (LIMIT, "limit", "┄"),
              (INCIDENT_KEY, "incident", "█")]
    incident_verbs = ("deploy", "done")
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "streams": Table(sort=ST_END, times=(ST_END,)),
        "instances": Table(sort=IN_SIGTERM, times=(IN_SIGTERM, IN_EXIT)),
        "samples": Table(sort=S_T, times=(S_T,)),
        "hits": Table(sort=HIT_T0, times=(HIT_T0, HIT_T1)),
    }
    goals = GOALS
    chart_top = 60.0

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 300.0))

    @property
    def one(self) -> float:
        """Requests per second one instance gets."""
        return self.rate / INSTANCES

    def start(self, variant: str, gen: int = 0) -> Run:
        run = super().start(variant, gen)
        run.data["rate"] = self.rate
        return run

    # ---------------------------------------------------------------- incidents

    def slot_of(self, run: Run, inc: Incident) -> int:
        rows = run.rows("hits", inc.t0 - 1e-6, inc.t0 + 1e-6)
        return rows[0][HIT_SLOT] if rows else 0

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "done")

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(inc.kind), n=inc.index + 1)

    def _add_incident_events(self, run: Run, inc: Incident) -> None:
        run.data.setdefault("slots", {})[inc.index] = self.slot_of(run, inc)
        super()._add_incident_events(run, inc)

    def incident_text(self, inc: Incident, start: bool) -> str:
        run = next((r for r in self.runs.values() if inc in r.incidents), None)
        slot = run.data.get("slots", {}).get(inc.index, 0) if run else 0
        if inc.kind == "deploy":
            if start:
                return self.s("deploy_start", n=round(inc.severity), cause=self.cause(inc))
            return self.s("deploy_end")
        key = "drain" if inc.kind == "drain" else "scale"
        if start:
            return self.s(f"{key}_start", slot=slot, cause=self.cause(inc))
        return self.s(f"{key}_end", slot=slot)

    def warnings(self, run: Run, inc: Incident):
        out = []
        for s in range(int(inc.t0), int(inc.t1) + 1):
            failed = run.series("failed", s, s + 1)[0]
            if failed >= WARN_FAILED:
                rows = [r for r in _ended(run, s, s + 1) if not r[REQ_OK]]
                slots = [r[REQ_SLOT] for r in rows if r[REQ_SLOT] >= 0]
                slot = max(set(slots), key=slots.count) if slots else 0
                out.append((s + 1.0, self.s("warn_failed", n=failed, slot=slot)))
                break
        for r in run.rows("instances", inc.t0 - EDGE, inc.t1):
            if r[IN_KILLED]:
                out.append((r[IN_EXIT], self.s("warn_killed", slot=r[IN_SLOT], cut=r[IN_CUT])))
                break
            if r[IN_CUT]:
                out.append((r[IN_EXIT], self.s("warn_cut", slot=r[IN_SLOT], cut=r[IN_CUT])))
                break
        return out

    # ---------------------------------------------------------------- the fleet at t

    def sample_at(self, run: Run, t: float) -> tuple | None:
        rows = run.rows("samples", t - 2 * SAMPLE, t + 1e-9)
        return rows[-1] if rows else None

    def fleet(self, run: Run, t: float) -> tuple[tuple[int, ...], int, tuple[int, ...]]:
        """(the state of each slot, instances serving, in flight per slot) at t."""
        s = self.sample_at(run, t)
        if s is None:
            return (SERVING,) * INSTANCES, INSTANCES, (0,) * INSTANCES
        return s[S_STATES], s[S_SERVING], s[S_FLYING]

    def focus(self, run: Run, t: float) -> tuple[int, int]:
        """The slot worth naming at t, and its state: refusing first, then leaving, draining, starting."""
        states, _, _ = self.fleet(run, t)
        for want in (REFUSING, LEAVING, DRAINING, STARTING):
            if want in states:
                return states.index(want), want
        return -1, SERVING

    def cut_at(self, run: Run, t: float, back: float) -> list[tuple]:
        """Instances that exited with work in flight in (t - back, t]."""
        span = run.max_dur.get("instances", 0.0)
        return [r for r in run.rows("instances", t - back - span, t + 1e-9)
                if t - back < r[IN_EXIT] <= t and r[IN_CUT]]

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("ask", r[REQ_START])
            if r[REQ_OK] and r[REQ_OLD]:
                run.add("old_served", r[REQ_START])
            if r[REQ_OK]:
                run.add("served", r[REQ_END])
            else:
                run.add("failed", r[REQ_END])
                if r[REQ_OUT] == CUT:
                    run.add("cut", r[REQ_END])
        for r in tables["streams"]:
            if r[ST_OUT] == CUT:
                run.add("cut", r[ST_END])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        _, serving, flying = self.fleet(run, t)

        def errors_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v > lab.ERRORS_MAX else "warn" if v > 0 else "ok"

        def errors_s(s: int):
            ok, bad = run.series("served", s, s + 1)[0], run.series("failed", s, s + 1)[0]
            v = bad / (ok + bad) if ok + bad else None
            return (v or 0.0), errors_state(v)

        errors = _share(_ended(run, t - 5, t))

        def cut_s(s: int):
            v = run.series("cut", s, s + 1)[0]
            return v, "bad" if v > lab.CUT_MAX else "ok"

        cut = sum(run.series("cut", int(t) - 5, int(t)))

        def serving_state(n: int) -> str:
            return "bad" if n < lab.CAPACITY_MIN else "warn" if n < INSTANCES else "ok"

        def serving_s(s: int):
            rows = run.rows("samples", s, s + 1)
            n = min((r[S_SERVING] for r in rows), default=INSTANCES)
            return INSTANCES - n, serving_state(n)

        tiles = [
            Tile(self.s("tile_errors"), "–" if errors is None else _pct(errors), f"≤{lab.ERRORS_MAX:.1%}",
                 errors_state(errors), history(run, t, errors_s)),
            Tile(self.s("tile_cut"), f"{cut:.0f}", f"={lab.CUT_MAX}", "bad" if cut > lab.CUT_MAX else "ok",
                 history(run, t, cut_s)),
            Tile(self.s("tile_serving"), f"{serving}/{INSTANCES}", f"≥{lab.CAPACITY_MIN}", serving_state(serving),
                 history(run, t, serving_s)),
        ]

        last = run.rows("requests", t - 1, t)
        new = sum(1 for r in last if not r[REQ_OLD] and r[REQ_OK])
        old = sum(1 for r in last if r[REQ_OLD] and r[REQ_OK])
        failed = sum(1 for r in last if not r[REQ_OK])
        bars = [
            Bar(self.s("bar_new"), [(new, WHITE)]),
            Bar(self.s("bar_old"), [(old, EXTRA2)]),
            Bar(self.s("bar_failed"), [(failed, RED)]),
        ]
        headline, colour = self._headline(run, t, failed, flying)
        return Traffic(tiles, bars, self.one, self.s("limit_one", n=round(self.one)), headline, colour,
                       title=self.s("toplist"))

    def _headline(self, run: Run, t: float, failed: int, flying: tuple[int, ...]):
        cut = self.cut_at(run, t, 1.0)
        if cut:
            return self.s("head_cut", slot=cut[-1][IN_SLOT], n=cut[-1][IN_CUT]), RED
        slot, state = self.focus(run, t)
        if failed:
            if state == REFUSING:
                return self.s("head_failed", n=failed, slot=slot), RED
            return self.s("head_failed_any", n=failed), RED
        if state in (LEAVING, DRAINING):
            key = "head_waiting" if state == LEAVING else "head_draining"
            return self.s(key, slot=slot, n=flying[slot]), EXTRA2
        if state == STARTING:
            return self.s("head_starting", slot=slot), PURPLE
        return self.s("head_steady", n=INSTANCES), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "requests", REQ_START, REQ_END, REQ_OK, t,
                                  busy=round(self.rate * 0.3))

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA2, run.hist.get("old_served", [])), (RED, run.hist.get("failed", []))]

    def chart_limit(self):
        return self.one, self.s("limit_one", n=round(self.one))

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = GracefulShutdownWorld
