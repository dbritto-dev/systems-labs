"""World for lab message_queue_consumers. Its words are in labs/message_queue_consumers/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.message_queue_consumers import lab
from labs.message_queue_consumers.scenario import DONE, LOST, PARKED
from live.canvas import (
    BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, PURPLE, RED, WHITE,
)
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, below,
    fmt_int, history, percentile,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
INF = float("inf")

JOB_ID, JOB_SENT, JOB_RECV, JOB_END, JOB_OUTCOME, JOB_RECEIVES, JOB_TRIES, JOB_DUP, JOB_POISON = range(9)
TRY_START, TRY_ID, TRY_N, TRY_END, TRY_RESULT, TRY_PROC, TRY_DUP, TRY_POISON = range(8)
DEP_T, DEP_VISIBLE, DEP_INFLIGHT, DEP_OLDEST, DEP_BUSY, DEP_DOWN = range(6)
DOWN_T0, DOWN_PROC, DOWN_T1 = range(3)

_s = strings("message_queue_consumers")  # one of the lab's STRINGS, for the goal measures below


def ended_by(row: tuple, upto: float) -> bool:
    """The job had finished (acked, lost or parked) by `upto`."""
    return row[JOB_END] is not None and row[JOB_END] <= upto


def age(row: tuple, upto: float) -> float:
    """How long a message waited before a worker first picked it up, as known at `upto`."""
    recv = row[JOB_RECV]
    if recv is not None and recv <= upto:
        return recv - row[JOB_SENT]
    return upto - row[JOB_SENT]  # still waiting (inf once the run has moved on without it)


def try_colour(row: tuple):
    """A try's colour: white the first delivery, oranges for redeliveries, deep orange a duplicate."""
    if row[TRY_DUP]:
        return EXTRA3
    return WHITE if row[TRY_N] <= 1 else EXTRA1 if row[TRY_N] == 2 else EXTRA2


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _sent(run: Run, inc: Incident, upto: float, window=_window) -> list[tuple]:
    a, b = window(inc)
    return run.rows("jobs", a, min(b, upto))


def _baseline(run: Run, inc: Incident, upto: float):
    done = [j for j in _sent(run, inc, upto, _before) if ended_by(j, upto)]
    if not done:
        return NO_VALUE
    v = sum(1 for j in done if j[JOB_OUTCOME] == DONE) / len(done)
    return v, f"{v:.0%}"


def _lost_rows(run: Run, inc: Incident, upto: float) -> list[tuple]:
    return [j for j in _sent(run, inc, upto) if j[JOB_OUTCOME] == LOST and ended_by(j, upto)]


def _lost(run: Run, inc: Incident, upto: float):
    if not _sent(run, inc, upto):
        return NO_VALUE
    n = len(_lost_rows(run, inc, upto))
    return n, fmt_int(n)


def _dups(run: Run, inc: Incident, upto: float):
    seen = [j for j in _sent(run, inc, upto) if ended_by(j, upto) or (j[JOB_RECV] or INF) <= upto]
    if not seen:
        return NO_VALUE
    # A job is a duplicate once a second try started while another ran (or after it was done).
    n = sum(1 for j in seen if j[JOB_DUP] and _dup_seen(run, j, upto))
    v = n / len(seen)
    return v, f"{v:.1%}"


def _dup_seen(run: Run, job: tuple, upto: float) -> bool:
    """Its first duplicate try had started by `upto` (the tries table says when)."""
    if upto == INF:
        return True
    return any(r[TRY_DUP] and r[TRY_ID] == job[JOB_ID] for r in run.rows("tries", job[JOB_SENT], upto))


def _age(run: Run, inc: Incident, upto: float):
    v = percentile([age(j, upto) for j in _sent(run, inc, upto)], 99)
    if v is None:
        return NO_VALUE
    return v, "∞" if v == INF else f"{v:.1f}s"


def _doomed_age(run: Run, inc: Incident, upto: float) -> bool:
    a, b = _window(inc)
    jobs = run.rows("jobs", a, b)
    if not jobs:
        return False
    late = sum(1 for j in jobs if j[JOB_SENT] <= upto and age(j, upto) >= lab.AGE_MAX)
    return late > len(jobs) * 0.01  # more than 1% already waited too long: the p99 cannot pass


def _dlq(run: Run, inc: Incident, upto: float):
    jobs = _sent(run, inc, upto)
    good = sum(1 for j in jobs if j[JOB_OUTCOME] == PARKED and not j[JOB_POISON] and ended_by(j, upto))
    if good:
        return -good, _s("good_parked", n=good)
    poison = [j for j in jobs if j[JOB_POISON]]
    if not poison:
        return None, _s("none")
    parked = sum(1 for j in poison if j[JOB_OUTCOME] == PARKED and ended_by(j, upto))
    return parked / len(poison), _s("parked", n=parked, of=len(poison))


def _doomed_dlq(run: Run, inc: Incident, upto: float) -> bool:
    return any(j[JOB_OUTCOME] == PARKED and not j[JOB_POISON] and ended_by(j, upto) for j in _sent(run, inc, upto))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), settle_extra=5.0, key="baseline"),
    GoalSpec("", "during", "", _window, _lost, lambda v: v == 0,
             doomed=lambda run, inc, upto: bool(_lost_rows(run, inc, upto)), settle_extra=lab.SETTLE, key="lost"),
    GoalSpec("", "during", "", _window, _dups, at_most(lab.DUP_MAX),
             settle_extra=lab.SETTLE, key="dups"),
    GoalSpec("", "during", "", _window, _age, below(lab.AGE_MAX),
             doomed=_doomed_age, settle_extra=lab.SETTLE, key="age"),
    GoalSpec("", "after", "", _window, _dlq, lambda v: v is None or v >= lab.PARK_MIN,
             doomed=_doomed_dlq, settle_extra=lab.DLQ_SETTLE, key="dlq"),
]


class MessageQueueWorld(World):
    id = "message_queue_consumers"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "first"), ([EXTRA1, EXTRA2], "redelivered"),
              (EXTRA3, "duplicate"), (GREEN, "acked"), (RED, "lost"), (PURPLE, "parked"),
              (LIMIT, "limit", "┄"), (DOWN_KEY, "incident", "█")]
    tables = {
        "jobs": Table(sort=JOB_SENT, times=(JOB_SENT, JOB_END)),
        "tries": Table(sort=TRY_START, times=(TRY_START, TRY_END)),
        "depth": Table(sort=DEP_T, times=(DEP_T,)),
        "downs": Table(sort=DOWN_T0, times=(DOWN_T0, DOWN_T1)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 40.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for j in tables["jobs"]:
            run.add("sent", j[JOB_SENT])
            if j[JOB_END] is None:
                continue
            outcome = j[JOB_OUTCOME]
            run.add({DONE: "served", LOST: "failed", PARKED: "parked"}[outcome], j[JOB_END])
            if j[JOB_DUP]:
                run.add("dup_jobs", j[JOB_END])
            run.add("ended", j[JOB_END])
        for r in tables["tries"]:
            run.add("dup_tries" if r[TRY_DUP] else "first_tries" if r[TRY_N] <= 1 else "retries", r[TRY_START])

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", rate=inc.severity, seconds=inc.severity, share=inc.severity,
                      cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        jobs = run.rows("jobs", *_window(inc))
        out = []
        lost = sum(1 for j in jobs if j[JOB_OUTCOME] == LOST)
        if lost:
            out.append((inc.t1, self.s("warn_lost", n=lost)))
        stuck = sum(1 for j in jobs if j[JOB_END] is None)
        if stuck:
            out.append((inc.t1, self.s("warn_stuck", n=stuck)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < max(i.t1, i.t0 + 1.0)), None)

    # ---------------------------------------------------------------- the queue at t

    def depth_at(self, run: Run, t: float) -> tuple | None:
        """The latest sample of the queue at or before t."""
        rows = run.rows("depth", t - 1.0, t + 1e-9)
        return rows[-1] if rows else None

    def down_at(self, run: Run, t: float) -> set[int]:
        """Worker processes that are down at t."""
        return {d[DOWN_PROC] for d in run.rows("downs", t - 10.0, t + 1e-9) if d[DOWN_T1] > t}

    def busy_at(self, run: Run, t: float) -> dict[int, int]:
        """Jobs running at t, per worker process."""
        busy: dict[int, int] = {}
        for r in run.active("tries", t, TRY_END):
            busy[r[TRY_PROC]] = busy.get(r[TRY_PROC], 0) + 1
        return busy

    def stuck(self, run: Run) -> list[tuple]:
        """Messages still in the queue when their minute was handed out (poison retried forever)."""
        return run.data.get("stuck", [])

    def _merge(self, run: Run, name: str, spec: Table, new: list[tuple]) -> None:
        super()._merge(run, name, spec, new)
        if name == "jobs":
            stuck = run.data.setdefault("stuck", [])
            stuck += [j for j in new if j[JOB_END] is None]
            del stuck[:-500]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = run.max_dur.get("jobs", 0.0)

        def ended(a: float, b: float) -> list[tuple]:
            return [j for j in run.rows("jobs", a - span, b) if j[JOB_END] is not None and a <= j[JOB_END] < b]

        recent = ended(t - 10, t)
        lost = sum(1 for j in recent if j[JOB_OUTCOME] == LOST)

        def lost_s(s: int):
            v = run.series("failed", s, s + 1)[0]
            return v, "bad" if v else "ok"

        dups = sum(1 for j in recent if j[JOB_DUP]) / len(recent) if recent else 0.0

        def dup_state(v: float) -> str:
            return "bad" if v > lab.DUP_MAX else "warn" if v > 0 else "ok"

        def dups_s(s: int):
            n, d = run.series("ended", s, s + 1)[0], run.series("dup_jobs", s, s + 1)[0]
            v = d / n if n else 0.0
            return v, dup_state(v)

        def ages(a: float, b: float) -> float | None:
            return percentile([age(j, b) for j in run.rows("jobs", a, b)], 99)

        p99 = ages(t - 10, t)

        def age_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v >= lab.AGE_MAX else "warn" if v >= lab.AGE_MAX / 2 else "ok"

        def age_s(s: int):
            v = ages(s, s + 1)
            return min(v or 0.0, 10.0), age_state(v)

        tiles = [
            Tile(self.s("tile_lost"), str(lost), "=0", "bad" if lost else "ok", history(run, t, lost_s)),
            Tile(self.s("tile_dups"), f"{dups:.0%}", "<1%", dup_state(dups), history(run, t, dups_s)),
            Tile(self.s("tile_age"), "–" if p99 is None else f"{p99:.1f}s", "<1s", age_state(p99),
                 history(run, t, age_s)),
        ]
        sent = run.count("jobs", t - 1, t)
        tries = run.rows("tries", t - 1, t)
        first = sum(1 for r in tries if r[TRY_N] <= 1 and not r[TRY_DUP])
        dup = sum(1 for r in tries if r[TRY_DUP])
        out = ended(t - 1, t)
        by = {k: sum(1 for j in out if j[JOB_OUTCOME] == k) for k in (DONE, PARKED, LOST)}
        bars = [
            Bar(self.s("bar_sent"), [(float(sent), WHITE)]),
            Bar(self.s("bar_tries"), [(float(first), WHITE), (float(len(tries) - first - dup), EXTRA2),
                                      (float(dup), EXTRA3)]),
            Bar(self.s("bar_out"), [(float(by[DONE]), GREEN), (float(by[PARKED]), PURPLE), (float(by[LOST]), RED)]),
        ]
        inc = self.incident_at(variant, t)
        dep = self.depth_at(run, t)
        oldest = dep[DEP_OLDEST] if dep else 0.0
        if lost:
            headline, colour = self.s("head_lost", n=lost), RED
        elif dups > lab.DUP_MAX:
            headline, colour = self.s("head_dups", share=dups), EXTRA3
        elif oldest > 20:
            headline, colour = self.s("head_old", seconds=oldest), EXTRA2
        elif inc is not None:
            headline, colour = self.s(f"head_{inc.kind}"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=self.rate * 2.5)

    def user_stats(self, variant: str, t: float):
        run = self.runs[variant]
        dep = self.depth_at(run, t)
        queued = (dep[DEP_VISIBLE] + dep[DEP_INFLIGHT]) if dep else 0
        p99 = percentile([age(j, t) for j in run.rows("jobs", t - 5, t)], 99)
        return [
            (self.s("stat_done"), fmt_int(run.total("served", t)), GREEN),
            (self.s("stat_lost"), fmt_int(run.total("failed", t)), RED if run.total("failed", t) else MUTED),
            (self.s("stat_queued"), fmt_int(queued), EXTRA2 if queued > 50 else WHITE),
            (self.s("stat_dlq"), fmt_int(run.total("parked", t)), PURPLE if run.total("parked", t) else MUTED),
            (self.s("stat_age"), "–" if p99 is None else f"{p99:.1f}s", WHITE),
        ]

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("first_tries", [])), (EXTRA2, run.hist.get("retries", [])),
                (EXTRA3, run.hist.get("dup_tries", [])), (RED, run.hist.get("failed", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    chart_top = 80.0

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = MessageQueueWorld
