"""World for lab transactional_outbox. Its words are in labs/transactional_outbox/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.transactional_outbox import lab
from labs.transactional_outbox.scenario import (
    AGAIN, DROPPED, GHOST, PHANTOM, POD, REBALANCED, RELAY_ONLY, SHIPPED, SKIPPED,
)
from live.canvas import BLUE, EXTRA1, EXTRA3, GREEN, IDLE_DOT, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, baseline_window, below, history,
    percentile,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
INF = float("inf")
BUSY_OUTBOX = 50  # unsent outbox rows that make the headline talk about the backlog

O_ID, O_START, O_END, O_OUTCOME, O_COMMIT, O_FIRST, O_EFFECTS, O_PUBS = range(8)
P_T, P_ORDER, P_WHO, P_OK, P_REPEAT = range(5)
D_T, D_ORDER, D_KIND = range(3)
POLL_T, POLL_N = range(2)
B_T, B_N = range(2)
K_T, K_BACK, K_WHAT = range(3)

_s = strings("transactional_outbox")  # one of the lab's STRINGS, for the goal measures below


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _dup_window(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1 + lab.DUP_TAIL


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER


def _saved(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Orders that started in [a, b) and were saved by `upto`."""
    return [o for o in run.rows("orders", a, min(b, upto)) if o[O_COMMIT] is not None and o[O_COMMIT] <= upto]


def _shipped(o: tuple, upto: float) -> bool:
    return o[O_FIRST] is not None and o[O_FIRST] <= upto


def _baseline(run: Run, inc: Incident, upto: float):
    saved = _saved(run, *_before(inc), upto)
    if not saved:
        return NO_VALUE
    v = sum(1 for o in saved if _shipped(o, upto)) / len(saved)
    return v, f"{v:.0%}"


def _lost(run: Run, inc: Incident, upto: float):
    saved = _saved(run, *_during(inc), upto)
    if not saved:
        return NO_VALUE
    n = sum(1 for o in saved if not _shipped(o, upto))
    final = upto >= inc.t1 + lab.SETTLE
    return n, (_s("count", n=n) if final or not n else _s("on_the_way", n=n))


def _doomed_lost(run: Run, inc: Incident, upto: float) -> bool:
    """A saved order whose event was dropped (no publish, no outbox row) is lost for good."""
    a, b = _during(inc)
    return any(o[O_OUTCOME] == DROPPED and o[O_END] <= upto for o in run.rows("orders", a, min(b, upto)))


def _phantoms(run: Run, a: float, b: float, upto: float) -> int:
    return sum(1 for o in run.rows("orders", a, min(b, upto)) if o[O_OUTCOME] == PHANTOM and o[O_END] <= upto)


def _phantom(run: Run, inc: Incident, upto: float):
    if upto <= inc.t0:
        return NO_VALUE
    n = _phantoms(run, *_during(inc), upto)
    return n, _s("count", n=n)


def _doomed_phantom(run: Run, inc: Incident, upto: float) -> bool:
    return _phantoms(run, *_during(inc), upto) > 0


def _dups(run: Run, a: float, b: float, upto: float) -> int:
    return sum(1 for d in run.rows("deliveries", a, min(b, upto)) if d[D_KIND] == AGAIN)


def _dup(run: Run, inc: Incident, upto: float):
    if upto <= inc.t0:
        return NO_VALUE
    n = _dups(run, *_dup_window(inc), upto)
    return n, _s("count", n=n)


def _doomed_dup(run: Run, inc: Incident, upto: float) -> bool:
    return _dups(run, *_dup_window(inc), upto) > 0


def _lag(run: Run, inc: Incident, upto: float):
    saved = _saved(run, *_after(inc), upto)
    if not saved:
        return NO_VALUE
    times = [(o[O_FIRST] if _shipped(o, upto) else upto) - o[O_COMMIT] for o in saved]
    v = percentile(times, 99)
    return v, "∞" if v == INF else f"{v:.1f}s"


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), settle_extra=lab.SETTLE, key="baseline"),
    GoalSpec("", "during", "", _during, _lost, lambda v: v == 0,
             doomed=_doomed_lost, settle_extra=lab.SETTLE, key="lost"),
    GoalSpec("", "during", "", _during, _phantom, lambda v: v == 0,
             doomed=_doomed_phantom, settle_extra=lab.SETTLE, key="phantom"),
    GoalSpec("", "during", "", _dup_window, _dup, lambda v: v == 0,
             doomed=_doomed_dup, settle_extra=lab.SETTLE, key="dup"),
    GoalSpec("", "after", "", _after, _lag, below(lab.LAG_MAX), settle_extra=lab.SETTLE, key="lag"),
]


class OutboxWorld(World):
    id = "transactional_outbox"
    view = "pipeline"
    stage_colours = (RED, EXTRA3, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "event"), (EXTRA1, "republished"), (EXTRA3, "twice"),
              (RED, "bad"), (GREEN, "shipped"), (MUTED, "skipped"), (LIMIT, "limit", "┄"),
              (DOWN_KEY, "incident", "█")]
    tables = {
        "orders": Table(sort=O_START, times=(O_START, O_END)),
        "publishes": Table(sort=P_T, times=(P_T,)),
        "deliveries": Table(sort=D_T, times=(D_T,)),
        "polls": Table(sort=POLL_T, times=(POLL_T,)),
        "backlog": Table(sort=B_T, times=(B_T,)),
        "kills": Table(sort=K_T, times=(K_T, K_BACK)),
    }
    goals = GOALS

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 50.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for o in tables["orders"]:
            run.add("orders", o[O_START])
            run.add("served" if o[O_COMMIT] is not None else "failed", o[O_END])
            if o[O_COMMIT] is not None:
                run.add("saved", o[O_COMMIT])
            if o[O_OUTCOME] == DROPPED:
                run.add("dropped", o[O_END])
            elif o[O_OUTCOME] == PHANTOM:
                run.add("phantoms", o[O_END])
        for p in tables["publishes"]:
            run.add("pub_failed" if not p[P_OK] else "pub_again" if p[P_REPEAT] else "pub_first", p[P_T])
        names = {SHIPPED: "shipped", AGAIN: "again", SKIPPED: "skipped", GHOST: "ghost"}
        for d in tables["deliveries"]:
            run.add(names[d[D_KIND]], d[D_T])

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", every=inc.severity, share=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        a, b = _during(inc)
        lost = sum(1 for o in run.rows("orders", a, b) if o[O_COMMIT] is not None and o[O_FIRST] is None)
        out = []
        if lost:
            out.append((inc.t1, self.s("warn_lost", n=lost)))
        twice = _dups(run, *_dup_window(inc), INF)
        if twice:
            out.append((inc.t1, self.s("warn_twice", n=twice)))
        return out

    # ---------------------------------------------------------------- what the pictures share

    def outbox_at(self, run: Run, t: float) -> int:
        rows = run.rows("backlog", t - 1, t + 1e-9)
        return rows[-1][B_N] if rows else 0

    def down_at(self, run: Run, t: float) -> set[int]:
        """What is down at t: POD (the order service and its relay), RELAY_ONLY, REBALANCED (shipping)."""
        return {k[K_WHAT] for k in run.rows("kills", t - run.max_dur.get("kills", 0.0) - 1e-9, t + 1e-9)
                if k[K_T] <= t < k[K_BACK]}

    def state_at(self, variant: str, t: float) -> tuple[str, tuple[int, int, int]]:
        """The one-word state of the system at t, and its colour."""
        run = self.runs[variant]
        down = self.down_at(run, t)
        inc = self.incident_at(variant, t)
        if POD in down:
            return self.s("state_restart"), RED
        if inc is not None and inc.kind == "broker":
            return self.s("state_broker"), RED
        if RELAY_ONLY in down:
            return self.s("state_relay"), EXTRA3
        if REBALANCED in down or (inc is not None and inc.kind == "rebalance"):
            return self.s("state_rebalance"), EXTRA3
        if inc is not None and inc.kind == "locks":
            return self.s("state_locks"), EXTRA3
        if inc is not None:
            return self.screen.STATES["degraded"], EXTRA3
        return self.screen.STATES["healthy"], GREEN

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = run.max_dur.get("orders", 0.0)
        ended = [o for o in run.rows("orders", t - 10 - span, t) if t - 10 <= o[O_END] < t]
        lost = sum(1 for o in ended if o[O_OUTCOME] == DROPPED)
        phantom = sum(1 for o in ended if o[O_OUTCOME] == PHANTOM)
        twice = sum(1 for d in run.rows("deliveries", t - 10, t) if d[D_KIND] == AGAIN)

        def per_second(name: str):
            def fn(s: int):
                v = run.series(name, s, s + 1)[0]
                return v, "bad" if v else "ok"
            return fn

        tiles = [
            Tile(self.s("tile_lost"), str(lost), "=0", "bad" if lost else "ok", history(run, t, per_second("dropped"))),
            Tile(self.s("tile_phantom"), str(phantom), "=0", "bad" if phantom else "ok",
                 history(run, t, per_second("phantoms"))),
            Tile(self.s("tile_twice"), str(twice), "=0", "bad" if twice else "ok", history(run, t, per_second("again"))),
        ]
        saved = sum(1 for o in run.rows("orders", t - 1 - span, t) if o[O_COMMIT] is not None and t - 1 <= o[O_COMMIT] < t)
        pubs = run.rows("publishes", t - 1, t)
        first = sum(1 for p in pubs if p[P_OK] and not p[P_REPEAT])
        again = sum(1 for p in pubs if p[P_OK] and p[P_REPEAT])
        kinds = [0, 0, 0, 0]
        for d in run.rows("deliveries", t - 1, t):
            kinds[d[D_KIND]] += 1
        bars = [
            Bar(self.s("bar_saved"), [(float(saved), WHITE)]),
            Bar(self.s("bar_published"), [(float(first), WHITE), (float(again), EXTRA1)]),
            Bar(self.s("bar_shipped"), [(float(kinds[SHIPPED]), WHITE), (float(kinds[AGAIN]), EXTRA3),
                                        (float(kinds[GHOST]), RED)]),
        ]
        outbox = self.outbox_at(run, t)
        if phantom:
            headline, colour = self.s("head_phantom", n=phantom), RED
        elif lost:
            headline, colour = self.s("head_lost", n=lost), RED
        elif twice:
            headline, colour = self.s("head_twice", n=twice), EXTRA3
        elif outbox >= BUSY_OUTBOX:
            headline, colour = self.s("head_outbox", n=outbox), EXTRA3
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "orders", O_START, O_END, O_COMMIT, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("shipped", [])), (EXTRA3, run.hist.get("again", [])),
                (RED, run.hist.get("ghost", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = OutboxWorld
