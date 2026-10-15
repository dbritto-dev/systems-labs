"""World for lab distributed_lock (leases and fencing tokens). Its words are in labs/distributed_lock/text/<lang>.py."""

from __future__ import annotations

from labs.distributed_lock import lab
from labs.distributed_lock.scenario import DRAIN, IDS, JOB_DEADLINE, LOCK_MSG
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, RED, RGB, WHITE
from live.worlds.base import (
    Bar, GoalSpec, Incident, Run, Settled, Table, Tile, Traffic, World, history,
)

JOB_START, JOB_ID, JOB_WORKER, JOB_END, JOB_OK = range(5)
W_SENT, W_WORKER, W_LEFT, W_ARRIVED, W_ACCEPTED, W_STALE, W_JOB, W_PART, W_GRANT = range(9)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_KIND = range(5)
G_T, G_JOB, G_WORKER, G_SEQ = range(4)
R_T, R_JOB = range(2)

SHOWN = 1.5  # seconds a corrupt or refused write keeps the picture on it
SLOW_STALL = 2.0  # seconds without a finished job (jobs waiting) before the lock looks stuck


def name(i: int) -> str:
    return IDS[i]


def corrupt(w: tuple) -> bool:
    """A write from a lost lock that the storage accepted over newer data."""
    return w[W_ACCEPTED] and w[W_STALE]


def refused(w: tuple) -> bool:
    """A write from a lost lock that the storage refused (fenced off)."""
    return not w[W_ACCEPTED] and w[W_STALE]


def landed(run: Run, a: float, b: float) -> list[tuple]:
    """Writes that reached the storage in [a, b) (a write can sit in the network up to ~DRAIN s)."""
    return [w for w in run.rows("writes", a - DRAIN, b) if a <= w[W_ARRIVED] < b]


def stall(run: Run, a: float, b: float) -> float:
    """The longest stretch in [a, b] with jobs waiting and none finishing (a job's end after b is unknown yet)."""
    events = []
    for r in run.rows("jobs", a - JOB_DEADLINE - 1, b):
        s, e = r[JOB_START], r[JOB_END]
        if e < a:
            continue
        events.append((max(s, a), 1, False))
        if e <= b:
            events.append((e, -1, r[JOB_OK]))
    events.sort(key=lambda x: (x[0], -x[1]))
    open_, since, longest = 0, a, 0.0
    for t, step, ok in events:
        if step > 0:
            open_ += 1
            if open_ == 1:
                since = t
            continue
        if ok:
            longest, since = max(longest, t - since), t
        open_ -= 1
        if open_ == 0:
            if not ok:
                longest = max(longest, t - since)
    if open_ > 0:
        longest = max(longest, b - since)
    return longest


def stall_at(run: Run, t: float) -> float:
    """How long jobs have been waiting at t with none finishing (0 when nobody waits)."""
    waiting = run.active("jobs", t, JOB_END)
    if not waiting:
        return 0.0
    span = run.max_dur.get("jobs", 0.0)
    last = max((r[JOB_END] for r in run.rows("jobs", t - span - 30, t + 1e-9) if r[JOB_OK] and r[JOB_END] <= t),
               default=0.0)
    return t - max(last, min(r[JOB_START] for r in waiting))


# ---------------------------------------------------------------- goals


def _corrupt_window(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.BEFORE, inc.t1 + lab.AFTER


def _corrupt(run: Run, inc: Incident, upto: float):
    a, b = _corrupt_window(inc)
    n = sum(1 for w in landed(run, a, min(b, upto)) if corrupt(w))
    return n, str(n)


def _window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.AFTER


def _stuck(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    if upto <= a:
        return None, "–"
    v = stall(run, a, min(b, upto))
    return v, f"{v:.1f}s"


def _done(run: Run, inc: Incident, upto: float):
    a, b = _window(inc)
    jobs = [r for r in run.rows("jobs", a, min(b, upto)) if r[JOB_END] <= upto]
    if not jobs:
        return None, "–"
    v = sum(1 for r in jobs if r[JOB_OK]) / len(jobs)
    return v, f"{v:.0%}"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "during", "", _corrupt_window, _corrupt, lambda v: v is not None and v <= lab.CORRUPT_MAX,
             doomed=lambda run, inc, upto: _corrupt(run, inc, upto)[0] > lab.CORRUPT_MAX,
             settle_extra=1.0, key="corrupt"),
    GoalSpec("", "during", "", _window, _stuck, lambda v: v is not None and v <= lab.STUCK_MAX,
             doomed=lambda run, inc, upto: (_stuck(run, inc, upto)[0] or 0.0) > lab.STUCK_MAX,
             settle_extra=0.5, key="stuck"),
    GoalSpec("", "after", "", _window, _done, lambda v: v is not None and v >= lab.DONE_MIN,
             settle_extra=JOB_DEADLINE + 0.5, key="done"),
]


class DistributedLockWorld(World):
    id = "distributed_lock"
    view = "fanin"  # who holds the lock, and where the late write lands, is the lesson
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(GREEN, "holder", "◉"), (EXTRA2, "frozen", "◉"), (RED, "down", "◉"), (BLUE, "lock_msg"),
              (WHITE, "write"), (EXTRA1, "late_write"), (RED, "corrupt"), (EXTRA2, "refused")]
    incident_verbs = ("pause", "wake")
    tables = {
        "jobs": Table(sort=JOB_START, times=(JOB_START, JOB_END)),
        "writes": Table(sort=W_SENT, times=(W_SENT, W_ARRIVED)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT, MSG_ARRIVED)),
        "grants": Table(sort=G_T, times=(G_T,)),
        "releases": Table(sort=R_T, times=(R_T,)),
    }
    goals = GOALS

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.victims: dict[float, int] = {}  # incident start -> the worker it hit

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 0.8))

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        self.victims.update(piece.get("victims", {}))  # before the incidents' words are written
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["jobs"]:
            run.add("asked", r[JOB_START])
            run.add("served" if r[JOB_OK] else "failed", r[JOB_END])
        for w in tables["writes"]:
            run.add("corrupt" if corrupt(w) else "refused" if refused(w) else
                    "written" if w[W_ACCEPTED] else "rejected", w[W_ARRIVED])
        for m in tables["msgs"]:
            if m[MSG_KIND] == LOCK_MSG:
                run.add("lock_msgs", m[MSG_SENT])

    def judge_stage(self, run: Run, first: list[Settled]) -> int:
        return lab.stage_of(*(r.ok for r in first))

    def victim(self, inc: Incident) -> str:
        return name(self.victims.get(inc.t0, 1))

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < i.t1), None)

    def sick_at(self, variant: str, t: float) -> tuple[int, str] | None:
        """(worker, kind) of the incident going on at t, if any."""
        inc = self.incident_at(variant, t)
        return None if inc is None else (self.victims.get(inc.t0, 1), inc.kind)

    def incident_title(self, inc: Incident) -> str:
        return self.screen.INCIDENT_TITLE.format(name=self.s(f"title_{inc.kind}"), n=inc.index + 1)

    def incident_verb(self, inc: Incident, start: bool) -> str:
        verbs = {"pause": ("pause", "wake"), "crash": ("crash", "back"), "delay": ("delay", "lands"),
                 "partition": ("cut", "heal")}[inc.kind]
        return self.word(verbs[0 if start else 1])

    def incident_text(self, inc: Incident, start: bool) -> str:
        worker = self.victim(inc)
        if start:
            return self.s(f"start_{inc.kind}", worker=worker, cause=self.cause(inc))
        return self.s(f"end_{inc.kind}", worker=worker)

    def warnings(self, run: Run, inc: Incident):
        bad = [w for w in landed(run, *_corrupt_window(inc)) if corrupt(w)]
        out = []
        if bad:
            w = bad[0]
            out.append((w[W_ARRIVED], self.s("warn_corrupt", worker=name(w[W_WORKER]), job=w[W_JOB])))
        fenced = [w for w in landed(run, *_corrupt_window(inc)) if refused(w)]
        if fenced:
            w = fenced[0]
            out.append((w[W_ARRIVED], self.s("warn_refused", worker=name(w[W_WORKER]), job=w[W_JOB])))
        return out

    # ---------------------------------------------------------------- what the pictures share

    def holder_at(self, run: Run, t: float) -> tuple | None:
        """The latest grant at or before t, unless its job has released the lock since: (job, worker, number)."""
        grants = run.rows("grants", t - 120, t + 1e-9)
        if not grants:
            return None
        g = grants[-1]
        if any(r[R_JOB] == g[G_JOB] for r in run.rows("releases", g[G_T], t + 1e-9)):
            return None
        return g[G_JOB], g[G_WORKER], g[G_SEQ]

    def recent_writes(self, run: Run, t: float, seconds: float = SHOWN) -> list[tuple]:
        return landed(run, t - seconds, t + 1e-9)

    def state_at(self, variant: str, t: float, short: bool = False) -> tuple[str, RGB]:
        """The words under the picture: a corrupt or refused write, a stuck lock, an incident, or healthy."""
        run = self.runs[variant]
        recent = self.recent_writes(run, t)
        words = self.screen.STATES
        stuck = stall_at(run, t)
        sick = self.sick_at(variant, t)
        if any(corrupt(w) for w in recent):
            return self.s("state_corrupt"), RED
        if any(refused(w) for w in recent):
            return self.s("state_refused"), EXTRA2
        if stuck > lab.STUCK_MAX:
            return self.s("state_stuck", s=min(99, int(stuck))), RED
        if sick is not None:
            worker, kind = name(sick[0]), sick[1]
            if kind == "pause":
                return self.s("state_frozen", worker=worker), EXTRA2
            if kind == "delay":
                return self.s("state_delayed"), EXTRA2
            key = "down" if kind == "crash" else "partitioned"
            return (words[key] if short else f"{words[key]}: {worker}"), RED
        return words["healthy"], GREEN

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]

        def corrupt_s(s: int):
            n = run.series("corrupt", s, s + 1)[0]
            return float(n), "bad" if n else "ok"

        def stuck_state(v: float) -> str:
            return "bad" if v > lab.STUCK_MAX else "warn" if v > SLOW_STALL else "ok"

        def stuck_s(s: int):
            v = stall_at(run, s + 1.0)
            return v, stuck_state(v)

        def done(a: float, b: float) -> float | None:
            ok, failed = sum(run.series("served", int(a), int(b))), sum(run.series("failed", int(a), int(b)))
            return ok / (ok + failed) if ok + failed else None

        def done_state(v: float | None) -> str:
            return "idle" if v is None else "ok" if v >= 0.95 else "warn" if v >= lab.DONE_MIN else "bad"

        def done_s(s: int):
            v = done(s - 4, s + 1)
            return (v or 0.0), done_state(v)

        bad = int(sum(run.series("corrupt", int(t) - 10, int(t))))
        stuck = stall_at(run, t)
        share = done(t - 10, t)
        tiles = [
            Tile(self.s("tile_corrupt"), str(bad), "=0", "bad" if bad else "ok", history(run, t, corrupt_s)),
            Tile(self.s("tile_stuck"), f"{stuck:.1f}s", f"≤{lab.STUCK_MAX:.0f}s", stuck_state(stuck),
                 history(run, t, stuck_s)),
            Tile(self.s("tile_done"), "–" if share is None else f"{share:.0%}", f"≥{lab.DONE_MIN:.0%}",
                 done_state(share), history(run, t, done_s)),
        ]
        last = landed(run, t - 1, t)
        good = sum(1 for w in last if w[W_ACCEPTED] and not w[W_STALE])
        bars = [
            Bar(self.s("bar_jobs"), [(float(run.count("jobs", t - 1, t)), WHITE)]),
            Bar(self.s("bar_lock"), [(float(sum(1 for m in run.rows("msgs", t - 1, t) if m[MSG_KIND] == LOCK_MSG)),
                                      BLUE)]),
            Bar(self.s("bar_writes"), [(float(good), WHITE), (float(sum(map(refused, last))), EXTRA2),
                                       (float(sum(map(corrupt, last))), RED)]),
        ]
        headline, colour = self._headline(variant, t, stuck)
        return Traffic(tiles, bars, 0.0, "", headline, colour, title=self.s("messages"))

    def _headline(self, variant: str, t: float, stuck: float) -> tuple[str, RGB]:
        run = self.runs[variant]
        recent = self.recent_writes(run, t, 5.0)
        bad = [w for w in recent if corrupt(w)]
        if bad:
            return self.s("head_corrupt", worker=name(bad[-1][W_WORKER])), RED
        fenced = [w for w in recent if refused(w)]
        if fenced:
            return self.s("head_refused", worker=name(fenced[-1][W_WORKER])), BLUE
        holder = self.holder_at(run, t)
        if stuck > SLOW_STALL:
            who = name(holder[1]) if holder else "?"
            return self.s("head_stuck", s=stuck, worker=who), RED if stuck > lab.STUCK_MAX else EXTRA2
        sick = self.sick_at(variant, t)
        if sick is not None:
            return self.s(f"head_{sick[1]}", worker=name(sick[0])), EXTRA2
        return self.s("head_ok"), MUTED

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "jobs", JOB_START, JOB_END, JOB_OK, t, busy=5)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(BLUE, run.hist.get("lock_msgs", [])), (WHITE, run.hist.get("written", [])),
                (EXTRA2, run.hist.get("refused", [])), (RED, run.hist.get("corrupt", []))]

    def legend_notes(self) -> list[str]:
        return [self.s("note_chart")]


WORLD = DistributedLockWorld
