"""World for lab event_loop_blocking. Its words are in labs/event_loop_blocking/text/<lang>.py."""

from __future__ import annotations

from labs.event_loop_blocking import lab
from labs.event_loop_blocking.scenario import (
    CPU,
    CPU_COL,
    DOWN,
    GC,
    GIL,
    HC_TIMEOUT,
    IO,
    KILLED,
    LIGHT,
    OWN,
    SHED,
    TIMED_OUT,
    TIMEOUT,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, PURPLE, RED, RGB, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, below, fmt_ms, history,
    percentile,
)

REQ_ID, REQ_START, REQ_END, REQ_ROUTE, REQ_OK, REQ_OUT = range(6)
HC_SENT, HC_END, HC_OK = range(3)
LAG_T, LAG_V = range(2)
BLK_T0, BLK_T1, BLK_CAUSE = range(3)
CALL_SUB, CALL_START, CALL_RAN, CALL_END, CALL_POOL, CALL_WORKER, CALL_NAME = range(7)
S_T, S_ALIVE, S_WAITING, S_RUNNING, S_POOLS, S_INFLIGHT = range(6)
P_PROCESS, P_WORKERS, P_RUNNING, P_WAITING, P_DEFAULT = range(5)
K_T, K_BACK = range(2)

# What holds the loop (or a worker), in every picture and the chart.
OWN_C: RGB = WHITE  # the loop's own work (parsing, rendering): short
IO_C: RGB = (86, 182, 194)  # blocking I/O: a sync DB driver, a sync HTTP client
CPU_C: RGB = EXTRA2  # CPU work: resizing, json.dumps
GIL_C: RGB = (214, 112, 190)  # waiting for the GIL (the loop slowed by a thread that computes)
GC_C: RGB = PURPLE  # garbage collection: the whole process stops
DOWN_C: RGB = RED  # killed, restarting
SHED_C: RGB = (229, 192, 76)  # a 503 at once: refused by a full queue
LOOP_OK: RGB = GREEN
INCIDENT_KEY: RGB = (110, 44, 56)
CAUSE_COLOURS = {OWN: OWN_C, IO: IO_C, CPU_COL: CPU_C, GIL: GIL_C, GC: GC_C}
CAUSE_OF = {"own": OWN, "pickle": OWN, "db": IO, "http": IO, "resize": CPU_COL, "report": CPU_COL, "gc": GC}
CHART = {OWN: "c_own", IO: "c_io", CPU_COL: "c_cpu", GIL: "c_gil", GC: "c_gc"}
CHART_CAP = 0.200  # seconds: the chart shows lag up to this (more is the same full bar)
STALL = 0.200  # a single stall of the loop this long is worth an event
STARTS = {"uploads": "upload", "slow_dep": "slow", "reports": "report", "gc": "gc"}  # VERBS keys
ENDS = {"uploads": "done", "slow_dep": "fast", "reports": "done", "gc": "calm"}


def lat(r: tuple, upto: float) -> float:
    """A request's latency as the user saw it at `upto`: a failed one counts as the whole timeout, one still
    running as what it has waited so far."""
    if r[REQ_END] > upto:
        return upto - r[REQ_START]
    return r[REQ_END] - r[REQ_START] if r[REQ_OK] else TIMEOUT


def _maxed(run: Run, name: str, t: float, v: float) -> None:
    """Per-second maximum (run.add sums)."""
    if t < 0:
        return
    s = int(t)
    h = run.hist.setdefault(name, [])
    if s >= len(h):
        h.extend([0.0] * (s + 1 - len(h)))
    h[s] = max(h[s], v)


def _ended(run: Run, a: float, b: float) -> list[tuple]:
    """Requests that ended in [a, b)."""
    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", a - span, b) if a <= r[REQ_END] < b]


# ---------------------------------------------------------------- goals


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _lag(run: Run, inc: Incident, upto: float):
    """p99 of the loop's lag (the probe, every 50 ms) during the incident."""
    v = percentile([r[LAG_V] for r in run.rows("lags", inc.t0, min(inc.t1, upto))], 99)
    return NO_VALUE if v is None else (v, fmt_ms(v))


def _health(run: Run, inc: Incident, upto: float):
    """Health checks sent during the incident that failed (late, unanswered, or refused while down)."""
    rows = [r for r in run.rows("health", inc.t0, min(inc.t1, upto)) if r[HC_END] <= upto]
    if not rows:
        return NO_VALUE
    v = sum(1 for r in rows if not r[HC_OK])
    return float(v), str(v)


def _health_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _health(run, inc, upto)
    return v is not None and v > lab.HEALTH_MAX


def _light(run: Run, inc: Incident, upto: float):
    """p99 latency of the light requests started during the incident."""
    v = percentile([lat(r, upto) for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_ROUTE] == LIGHT],
                   99)
    return NO_VALUE if v is None else (v, fmt_ms(v))


def _served(run: Run, inc: Incident, upto: float):
    """The share of the heavy requests (a blocking call) started during the incident that were answered in time."""
    rows = [r for r in run.rows("requests", inc.t0, min(inc.t1, upto)) if r[REQ_ROUTE] != LIGHT and r[REQ_END] <= upto]
    if not rows:
        return NO_VALUE
    v = sum(1 for r in rows if r[REQ_OK]) / len(rows)
    return v, f"{v:.0%}"


def _queued(run: Run, inc: Incident, upto: float):
    """The most calls waiting in the executors' queues at once during the incident."""
    rows = run.rows("samples", inc.t0, min(inc.t1, upto))
    if not rows:
        return NO_VALUE
    v = max(r[S_WAITING] for r in rows)
    return float(v), str(v)


def _queued_doomed(run: Run, inc: Incident, upto: float) -> bool:
    v, _ = _queued(run, inc, upto)
    return v is not None and v > lab.QUEUED_MAX


def _watched(run: Run, inc: Incident, upto: float):
    """The share of the incident's whole seconds with at least one lag report from your watchdog."""
    a, b = int(inc.t0), int(min(inc.t1, upto))
    if b <= a:
        return NO_VALUE
    seen = run.series("reports", a, b)
    v = sum(1 for x in seen if x) / (b - a)
    return v, f"{v:.0%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _during, _lag, below(lab.LAG_MAX), key="lag"),
    GoalSpec("", "during", "", _during, _health, at_most(lab.HEALTH_MAX),
             doomed=_health_doomed, settle_extra=HC_TIMEOUT + 0.5, key="health"),
    GoalSpec("", "during", "", _during, _light, below(lab.LIGHT_P99_MAX),
             settle_extra=lab.SETTLE, key="light"),
    GoalSpec("", "during", "", _during, _served, at_least(lab.SERVED_MIN),
             settle_extra=lab.SETTLE, key="served"),
    GoalSpec("", "during", "", _during, _queued, at_most(lab.QUEUED_MAX),
             doomed=_queued_doomed, key="queued"),
    GoalSpec("", "during", "", _during, _watched, at_least(lab.WATCHED_MIN), key="watched"),
]


class EventLoopWorld(World):
    id = "event_loop_blocking"
    view = "lanes"  # the users' view first: one loop, and everybody waits when it blocks
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), ([EXTRA1, EXTRA2, EXTRA3], "waits", "●"), (GREEN, "served"),
              (SHED_C, "shed"), (RED, "failed"), (OWN_C, "own", "█"), (IO_C, "io", "█"), (CPU_C, "cpu", "█"),
              (GIL_C, "gil", "█"), (GC_C, "gc", "█"), (LIMIT, "budget", "┄"), (INCIDENT_KEY, "incident", "█")]
    tables = {
        "requests": Table(sort=REQ_START, times=(REQ_START, REQ_END)),
        "health": Table(sort=HC_SENT, times=(HC_SENT, HC_END)),
        "lags": Table(sort=LAG_T, times=(LAG_T,)),
        "reports": Table(sort=0, times=(0,)),
        "blocks": Table(sort=BLK_T0, times=(BLK_T0, BLK_T1)),
        "calls": Table(sort=CALL_START, times=(CALL_START, CALL_END)),
        "samples": Table(sort=S_T, times=(S_T,)),
        "kills": Table(sort=K_T, times=(K_T, K_BACK)),
        "loop": Table(sort=0, times=(0,)),
    }
    goals = GOALS
    chart_top = 100.0

    # ---------------------------------------------------------------- incidents

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word((STARTS if start else ENDS).get(inc.kind, "upload"))

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(inc.kind), n=inc.index + 1)

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        sev = inc.severity
        return self.s(f"{inc.kind}_start", cores=sev, times=sev, ms=sev * 1000, cause=self.cause(inc))

    def incident_at(self, run: Run, t: float) -> Incident | None:
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    # ---------------------------------------------------------------- data

    def sample_at(self, run: Run, t: float) -> tuple | None:
        rows = run.rows("samples", t - 1.0, t + 1e-9)
        return rows[-1] if rows else None

    def down_at(self, run: Run, t: float) -> tuple | None:
        """The kill whose restart is not over at t, if any."""
        rows = run.rows("kills", t - run.max_dur.get("kills", 0.0) - 1e-9, t + 1e-9)
        return next((k for k in rows if k[K_T] <= t < k[K_BACK]), None)

    def stall_at(self, run: Run, t: float) -> tuple | None:
        """The loop stall going on at t (a blocking call, a GC pause), if any."""
        span = run.max_dur.get("blocks", 0.0)
        rows = run.rows("blocks", t - span - 1e-9, t + 1e-9)
        return next((b for b in reversed(rows) if b[BLK_T0] <= t < b[BLK_T1]), None)

    def lag_now(self, run: Run, t: float, back: float = 1.0) -> float | None:
        """The worst lag the probe saw in the last `back` seconds; a stall going on counts too."""
        rows = run.rows("lags", t - back, t + 1e-9)
        v = max((r[LAG_V] for r in rows), default=None)
        stall = self.stall_at(run, t)
        if stall is not None:
            v = max(v or 0.0, t - stall[BLK_T0])
        return v

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["requests"]:
            run.add("ask", r[REQ_START])
            route = r[REQ_ROUTE]
            run.add("ask_light" if route == LIGHT else "ask_cpu" if CPU[route] else "ask_io", r[REQ_START])
            out = r[REQ_OUT]
            if r[REQ_OK]:
                run.add("served", r[REQ_END])
            else:
                run.add("failed", r[REQ_END])
                run.add("shed" if out == SHED else "lost", r[REQ_END])
        for r in tables["health"]:
            if not r[HC_OK]:
                run.add("hc_fail", r[HC_SENT])
        for r in tables["lags"]:
            _maxed(run, "lagmax", r[LAG_T], r[LAG_V])
        for r in tables["reports"]:
            run.add("reports", r[0])
        for r in tables["samples"]:
            _maxed(run, "queued", r[S_T], r[S_WAITING])
        down: set[int] = set()
        for k in tables["kills"]:
            down.update(range(int(k[K_T]), int(k[K_BACK]) + 1))
        for row in tables["loop"]:
            s = row[0]
            for col in (OWN, IO, CPU_COL, GIL, GC):
                run.add(f"busy{col}", s, row[1 + col])
        # The chart: each second's worst lag, in the colour of what held the loop most that second.
        for s in range(int(piece["start"]), int(piece["end"])):
            if s in down or (run.data.get("down_until", -1) > s):
                run.add("c_down", s, CHART_CAP * 1000)
                continue
            lag = min(run.series("lagmax", s, s + 1)[0], CHART_CAP)
            busy = {col: run.series(f"busy{col}", s, s + 1)[0] for col in (IO, CPU_COL, GIL, GC)}
            col = max(busy, key=busy.get)
            run.add(CHART[col if busy[col] > 0.002 else OWN], s, lag * 1000)
        for k in tables["kills"]:
            run.data["down_until"] = max(run.data.get("down_until", -1), k[K_BACK])

    def warnings(self, run: Run, inc: Incident):
        out = []
        end = inc.t1 + lab.SETTLE
        kills = [k for k in run.rows("kills", inc.t0, end)]
        if kills:
            out.append((kills[0][K_T], self.s("warn_killed")))
        stalls = [b for b in run.rows("blocks", inc.t0, inc.t1) if b[BLK_T1] - b[BLK_T0] >= STALL]
        if stalls:
            b = max(stalls[:50], key=lambda b: b[BLK_T1] - b[BLK_T0])
            out.append((b[BLK_T1], self.s("warn_stall", ms=(b[BLK_T1] - b[BLK_T0]) * 1000,
                                          what=self.s(f"call_{b[BLK_CAUSE]}"))))
        for s in run.rows("samples", inc.t0, inc.t1):
            if s[S_WAITING] > lab.QUEUED_MAX:
                out.append((s[S_T], self.s("warn_queued", n=s[S_WAITING])))
                break
        for sec in range(int(inc.t0), int(inc.t1) + 1):
            shed = run.series("shed", sec, sec + 1)[0]
            if shed:
                out.append((sec + 1.0, self.s("warn_shed", n=shed)))
                break
        for r in run.rows("reports", inc.t0, inc.t1):
            if r[1] >= lab.LAG_MAX:
                out.append((r[0], self.s("warn_watchdog", ms=r[1] * 1000)))
                break
        return out

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        def lag_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.LAG_MAX else "warn" if v >= lab.LAG_MAX / 2 else "ok"

        def lag_s(sec: int):
            if self.down_at(run, sec + 0.5):
                return CHART_CAP, "bad"
            v = run.series("lagmax", sec, sec + 1)[0]
            return v, lag_state(v)

        lag = percentile([r[LAG_V] for r in run.rows("lags", t - 5, t)], 99)
        if self.down_at(run, t):
            lag = None

        def light_state(v: float | None) -> str:
            return ("idle" if v is None else "bad" if v >= lab.LIGHT_P99_MAX
                    else "warn" if v >= lab.LIGHT_P99_MAX / 2 else "ok")

        def light_of(rows: list[tuple]) -> float | None:
            return percentile([lat(r, 1e18) for r in rows if r[REQ_ROUTE] == LIGHT], 99)

        def light_s(sec: int):
            v = light_of(_ended(run, sec, sec + 1))
            return (v or 0.0), light_state(v)

        light = light_of(_ended(run, t - 5, t))

        def queued_state(v: float | None) -> str:
            return ("idle" if v is None else "bad" if v > lab.QUEUED_MAX
                    else "warn" if v > lab.QUEUED_MAX / 2 else "ok")

        def queued_s(sec: int):
            v = run.series("queued", sec, sec + 1)[0]
            return v, queued_state(v)

        sample = self.sample_at(run, t)
        queued = sample[S_WAITING] if sample is not None else None
        tiles = [
            Tile(self.s("tile_lag"), fmt_ms(lag) if lag is not None else "–", f"<{fmt_ms(lab.LAG_MAX)}",
                 lag_state(lag) if not self.down_at(run, t) else "bad", history(run, t, lag_s)),
            Tile(self.s("tile_light"), fmt_ms(light), f"<{fmt_ms(lab.LIGHT_P99_MAX)}", light_state(light),
                 history(run, t, light_s)),
            Tile(self.s("tile_queued"), "–" if queued is None else f"{queued:,}", f"≤{lab.QUEUED_MAX}",
                 queued_state(queued), history(run, t, queued_s)),
        ]
        started = run.rows("requests", t - 1, t)
        ended = _ended(run, t - 1, t)
        light_n = sum(1 for r in started if r[REQ_ROUTE] == LIGHT)
        cpu_n = sum(1 for r in started if r[REQ_ROUTE] != LIGHT and CPU[r[REQ_ROUTE]])
        bars = [
            Bar(self.s("bar_asked"), [(light_n, WHITE), (len(started) - light_n - cpu_n, IO_C), (cpu_n, CPU_C)]),
            Bar(self.s("bar_served"), [(sum(1 for r in ended if r[REQ_OK]), GREEN)]),
            Bar(self.s("bar_refused"), [(sum(1 for r in ended if r[REQ_OUT] == SHED), SHED_C),
                                        (sum(1 for r in ended if r[REQ_OUT] in (TIMED_OUT, KILLED, DOWN)), RED)]),
        ]
        headline, colour = self._headline(run, t, sample, lag)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("toplist"))

    def _headline(self, run: Run, t: float, sample: tuple | None, lag: float | None) -> tuple[str, RGB]:
        if self.down_at(run, t):
            return self.s("head_down"), RED
        stall = self.stall_at(run, t)
        if stall is not None and t - stall[BLK_T0] >= lab.LAG_MAX:
            return self.s("head_blocked", what=self.s(f"call_{stall[BLK_CAUSE]}"),
                          ms=(t - stall[BLK_T0]) * 1000), RED
        if lag is not None and lag >= lab.LAG_MAX:
            busy = {col: sum(run.series(f"busy{col}", int(t) - 5, int(t))) for col in (IO, CPU_COL, GIL, GC)}
            if max(busy, key=busy.get) == GC:
                return self.s("head_gc", ms=lag * 1000), GC_C
            return self.s("head_lag", ms=lag * 1000), EXTRA2
        if sample is not None and sample[S_WAITING] > lab.QUEUED_MAX:
            return self.s("head_queued", n=sample[S_WAITING]), EXTRA2
        shed = run.series("shed", int(t) - 1, int(t))[0]
        if shed:
            return self.s("head_shed", n=int(shed)), SHED_C
        s = int(t) - 1
        if run.series(f"busy{GIL}", s, s + 1)[0] > 0.01:
            return self.s("head_gil"), GIL_C
        return self.s("head_ok", ms=(lag or 0.0) * 1000), BLUE

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "requests", REQ_START, REQ_END, REQ_OK, t, busy=50)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(OWN_C, run.hist.get("c_own", [])), (IO_C, run.hist.get("c_io", [])),
                (CPU_C, run.hist.get("c_cpu", [])), (GIL_C, run.hist.get("c_gil", [])),
                (GC_C, run.hist.get("c_gc", [])), (DOWN_C, run.hist.get("c_down", []))]

    def chart_limit(self):
        return lab.LAG_MAX * 1000, self.s("limit_lag")

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart"), self.s("note_dots")]


WORLD = EventLoopWorld
