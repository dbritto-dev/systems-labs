"""World for lab cache_invalidation. Its words are in labs/cache_invalidation/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.cache_invalidation import lab
from labs.cache_invalidation.scenario import PHANTOM, STALE
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, IDLE_DOT, MUTED, RED, WHITE
from live.worlds.base import (
    NO_VALUE, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, at_most, baseline_window, history,
)
from live.worlds.base import Bar

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents

R_ID, R_START, R_END, R_APP, R_KEY, R_MISSED, R_VERDICT, R_FRESH = range(8)
W_START, W_END, W_APP, W_KEY, W_OK, W_SOURCE = range(6)
F_T, F_APP, F_KEY, F_RESULT = range(4)
P_T0, P_T1, P_APP = range(3)
A_T, A_STALE, A_ENTRIES, A_DB, A_UP = range(5)

_s = strings("cache_invalidation")  # one of the lab's STRINGS, for the goal measures below


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0, inc.t1


def _checked(inc: Incident) -> tuple[float, float]:
    """The incident, and a few seconds after it: what it left in the cache."""
    return inc.t0, inc.t1 + lab.CHECK


def _ended(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Reads that started in [a, b) and finished by `upto`."""
    return [r for r in run.rows("reads", a, min(b, upto)) if r[R_END] <= upto]


def _hits(run: Run, inc: Incident, upto: float):
    a, b = _before(inc)
    done = _ended(run, a, b, upto)
    if not done:
        return NO_VALUE
    v = sum(not r[R_MISSED] for r in done) / len(done)
    return v, f"{v:.0%}"


def _counter(verdict: int):
    def measure(run: Run, inc: Incident, upto: float):
        done = _ended(run, *_during(inc), upto)
        if not done:
            return NO_VALUE
        n = sum(r[R_VERDICT] == verdict for r in done)
        return n, _s("count", n=n)

    def doomed(run: Run, inc: Incident, upto: float) -> bool:
        return any(r[R_VERDICT] == verdict for r in _ended(run, *_during(inc), upto))

    return measure, doomed


_phantom, _doomed_phantom = _counter(PHANTOM)
_stale, _doomed_stale = _counter(STALE)


def _audits(run: Run, inc: Incident, upto: float) -> list[tuple]:
    a, b = _checked(inc)
    return [x for x in run.rows("audit", a, min(b, upto) + 1e-9) if x[A_T] > a]


def _entries(run: Run, inc: Incident, upto: float):
    rows = _audits(run, inc, upto)
    if not rows:
        return NO_VALUE
    n = max(x[A_STALE] for x in rows)
    return n, _s("count", n=n)


def _doomed_entries(run: Run, inc: Incident, upto: float) -> bool:
    return any(x[A_STALE] for x in _audits(run, inc, upto))


def _db(run: Run, inc: Incident, upto: float):
    rows = _audits(run, inc, upto)
    if not rows:
        return NO_VALUE
    n = max(x[A_DB] for x in rows)
    return n, _s("per_s", n=n)


def _doomed_db(run: Run, inc: Incident, upto: float) -> bool:
    return any(x[A_DB] > lab.DB_LIMIT for x in _audits(run, inc, upto))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _hits, at_least(lab.HIT_MIN), key="hits"),
    GoalSpec("", "during", "", _during, _phantom, lambda v: v == 0,
             doomed=_doomed_phantom, settle_extra=lab.SETTLE, key="phantom"),
    GoalSpec("", "during", "", _during, _stale, lambda v: v == 0,
             doomed=_doomed_stale, settle_extra=lab.SETTLE, key="stale"),
    GoalSpec("", "after", "", _checked, _entries, lambda v: v == 0,
             doomed=_doomed_entries, settle_extra=1.0, key="entries"),
    GoalSpec("", "during", "", _checked, _db, at_most(lab.DB_LIMIT),
             doomed=_doomed_db, settle_extra=1.0, key="db"),
]


class CacheInvalidationWorld(World):
    id = "cache_invalidation"
    view = "relay"  # opens with the relay picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(IDLE_DOT, "idle", "○"), (WHITE, "hit"), (EXTRA1, "miss"), (GREEN, "served"), (RED, "stale"),
              (BLUE, "write"), (EXTRA2, "refused"), (DOWN_KEY, "incident", "█")]
    tables = {
        "reads": Table(sort=R_START, times=(R_START, R_END)),
        "writes": Table(sort=W_START, times=(W_START, W_END)),
        "fills": Table(sort=F_T, times=(F_T,)),
        "pauses": Table(sort=P_T0, times=(P_T0, P_T1)),
        "audit": Table(sort=A_T, times=(A_T,)),
    }
    goals = GOALS
    chart_top = 100.0

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 300.0))

    # ---------------------------------------------------------------- data

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["reads"]:
            run.add("asks", r[R_START])
            run.add("served" if r[R_FRESH] else "failed", r[R_END])
            run.add("misses" if r[R_MISSED] else "hits", r[R_END])
            if not r[R_FRESH]:
                run.add("bad", r[R_END])
        for w in tables["writes"]:
            run.add("written" if w[W_OK] else "refused", w[W_END])
        for x in tables["audit"]:
            run.add("dbreads", x[A_T] - 0.5, x[A_DB])  # the second that ended at x[A_T]

    def incident_verb(self, inc: Incident, start: bool) -> str:
        return self.word(inc.kind if start else "calm")

    def incident_text(self, inc: Incident, start: bool) -> str:
        if not start:
            return self.s(f"{inc.kind}_end")
        return self.s(f"{inc.kind}_start", rate=inc.severity, times=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        reads = run.rows("reads", inc.t0, inc.t1)
        out = []
        phantom = sum(r[R_VERDICT] == PHANTOM for r in reads)
        stale = sum(r[R_VERDICT] == STALE for r in reads)
        if phantom:
            out.append((inc.t1, self.s("warn_phantom", n=phantom)))
        if stale:
            out.append((inc.t1, self.s("warn_stale", n=stale)))
        return out

    def incident_at(self, variant: str, t: float) -> Incident | None:
        run = self.runs.get(variant)
        if run is None:
            return None
        return next((i for i in reversed(run.incidents) if i.t0 <= t < max(i.t1, i.t0 + 1.0)), None)

    def audit_at(self, run: Run, t: float) -> tuple | None:
        """The latest check of the cache at or before t."""
        rows = run.rows("audit", t - 2.0, t + 1e-9)
        return rows[-1] if rows else None

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        span = run.max_dur.get("reads", 0.0)
        recent = [r for r in run.rows("reads", t - 10 - span, t) if t - 10 <= r[R_END] < t]
        bad = sum(1 for r in recent if not r[R_FRESH])
        hits = sum(1 for r in recent if not r[R_MISSED]) / len(recent) if recent else None
        audit = self.audit_at(run, t)
        keys = audit[A_STALE] if audit else 0

        def bad_s(s: int):
            v = run.series("bad", s, s + 1)[0]
            return v, "bad" if v else "ok"

        def hit_state(v: float | None) -> str:
            return "idle" if v is None else "bad" if v < lab.HIT_MIN else "warn" if v < 0.9 else "ok"

        def hits_s(s: int):
            h, m = run.series("hits", s, s + 1)[0], run.series("misses", s, s + 1)[0]
            v = h / (h + m) if h + m else None
            return (v or 0.0), hit_state(v)

        def keys_s(s: int):
            rows = run.rows("audit", s + 0.5, s + 1.5)
            v = rows[-1][A_STALE] if rows else 0
            return v, "bad" if v else "ok"

        tiles = [
            Tile(self.s("tile_stale"), f"{bad}", "=0", "bad" if bad else "ok", history(run, t, bad_s)),
            Tile(self.s("tile_hits"), "–" if hits is None else f"{hits:.0%}", f"≥{lab.HIT_MIN:.0%}",
                 hit_state(hits), history(run, t, hits_s)),
            Tile(self.s("tile_keys"), f"{keys}", "=0", "bad" if keys else "ok", history(run, t, keys_s)),
        ]
        ended = [r for r in run.rows("reads", t - 1 - span, t) if t - 1 <= r[R_END] < t]
        hit = sum(1 for r in ended if r[R_FRESH] and not r[R_MISSED])
        miss = sum(1 for r in ended if r[R_FRESH] and r[R_MISSED])
        stale = len(ended) - hit - miss
        wspan = run.max_dur.get("writes", 0.0)
        writes = [w for w in run.rows("writes", t - 1 - wspan, t) if t - 1 <= w[W_END] < t]
        ok = sum(1 for w in writes if w[W_OK])
        bars = [
            Bar(self.s("bar_reads"), [(float(hit), WHITE), (float(miss), EXTRA1), (float(stale), RED)]),
            Bar(self.s("bar_db"), [(float(audit[A_DB] if audit else 0), EXTRA1)]),  # against the limit tick
            Bar(self.s("bar_writes"), [(float(ok), BLUE), (float(len(writes) - ok), MUTED)]),
        ]
        inc = self.incident_at(variant, t)
        if bad:
            headline, colour = self.s("head_stale", n=bad), RED
        elif keys:
            headline, colour = self.s("head_keys", n=keys), RED
        elif inc is not None:
            headline, colour = self.s(f"head_{inc.kind}"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, lab.DB_LIMIT, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"))

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "reads", R_START, R_END, R_FRESH, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(EXTRA1, run.hist.get("dbreads", [])), (RED, run.hist.get("bad", []))]

    def chart_limit(self):
        return None  # the chart scales to the misses, so a few stale reads still show; the limit is a goal

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = CacheInvalidationWorld
