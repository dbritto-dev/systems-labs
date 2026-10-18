"""World for lab two_phase_commit. Its words are in labs/two_phase_commit/text/<lang>.py."""

from __future__ import annotations

from core.i18n import strings
from labs.two_phase_commit import lab
from labs.two_phase_commit.scenario import (
    ABORTED, COMMITTED, IN_DOUBT, M_ABORT, M_COMMIT, M_NO, M_YES, PARTIAL,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, LIMIT, MUTED, RED, WHITE
from live.worlds.base import (
    NO_VALUE, Bar, GoalSpec, Incident, Run, Table, Tile, Traffic, World, at_least, baseline_window, history,
)

DOWN_KEY = (110, 44, 56)  # the legend swatch for the shaded incidents
INF = float("inf")

(TX_ID, TX_START, TX_END, TX_STATUS, TX_OK, TX_REFUSED, TX_DELTAS, TX_APPLIED, TX_RESOLVED, TX_PREP,
 TX_CEND) = range(11)
MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED, MSG_KIND = range(5)
ST_T, ST_HELD, ST_DOUBT, ST_DOWN, ST_CUT, ST_MONEY = range(6)

_s = strings("two_phase_commit")  # one of the lab's STRINGS, for the goal measures below


def money(amount: float) -> str:
    """$1,234 or -$1,234."""
    return f"{'-' if amount < 0 else ''}${abs(int(amount)):,}"


def drift_at(row: tuple, t: float) -> int:
    """Money a transfer created (+) or destroyed (-) by time t: its writes applied by then. A transfer
    applied on every shard (or none) moves nothing: its writes add up to zero."""
    return sum(d for d, at in zip(row[TX_DELTAS], row[TX_APPLIED]) if 0 <= at <= t)


# ---------------------------------------------------------------- goals


_before = baseline_window(lab)


def _during(inc: Incident) -> tuple[float, float]:
    return inc.t0 - lab.LEAD, inc.t1  # transfers running when it starts are caught in it too


def _resolve(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.RESOLVE


def _after(inc: Incident) -> tuple[float, float]:
    return inc.t1, inc.t1 + lab.AFTER


def _rows(run: Run, a: float, b: float, upto: float) -> list[tuple]:
    """Transfers that started in [a, b) and ended by `upto`."""
    return [r for r in run.rows("txns", a, min(b, upto)) if r[TX_END] <= upto]


def _committed_share(rows: list[tuple]):
    if not rows:
        return NO_VALUE
    v = sum(1 for r in rows if r[TX_STATUS] == COMMITTED) / len(rows)
    return v, f"{v:.0%}"


def _baseline(run: Run, inc: Incident, upto: float):
    return _committed_share(_rows(run, *_before(inc), upto))


def _rolled(run: Run, inc: Incident, upto: float):
    refused = [r for r in _rows(run, *_during(inc), upto) if r[TX_REFUSED]]
    if not refused:
        return None, _s("none")  # no shard said no
    v = sum(1 for r in refused if all(at < 0 for at in r[TX_APPLIED])) / len(refused)
    return v, f"{v:.0%}"


def _partial(run: Run, inc: Incident, upto: float):
    rows = _rows(run, *_during(inc), upto)
    if not rows:
        return NO_VALUE
    n = sum(1 for r in rows if r[TX_STATUS] == PARTIAL)
    return n, str(n)


def _doomed_partial(run: Run, inc: Incident, upto: float) -> bool:
    return any(r[TX_STATUS] == PARTIAL for r in _rows(run, *_during(inc), upto))


def _money(run: Run, inc: Incident, upto: float):
    rows = [r for r in run.rows("txns", *_during(inc)) if r[TX_START] <= upto]
    if not rows:
        return NO_VALUE
    at = min(upto, inc.t1 + lab.RESOLVE)
    v = sum(abs(drift_at(r, at)) for r in rows)
    return v, money(v)


def _doubt(run: Run, inc: Incident, upto: float):
    """How long after the incident ended its transfers stayed in doubt (prepared, no decision)."""
    rows = [r for r in _rows(run, *_during(inc), upto) if any(p >= 0 for p in r[TX_PREP])]
    if not rows:
        return NO_VALUE
    v = max(INF if r[TX_RESOLVED] is None else max(0.0, r[TX_RESOLVED] - inc.t1) for r in rows)
    return v, "∞" if v == INF else f"{v:.1f}s"


def _completed(run: Run, inc: Incident, upto: float):
    return _committed_share(_rows(run, *_after(inc), upto))


# The rule and fix of each goal are text.GOALS[key].
GOALS = [
    GoalSpec("", "before", "", _before, _baseline, at_least(lab.BASELINE_MIN), settle_extra=lab.SETTLE, key="baseline"),
    GoalSpec("", "during", "", _during, _rolled, lambda v: v is None or v >= 1.0,
             settle_extra=lab.SETTLE, key="rolled"),
    GoalSpec("", "during", "", _during, _partial, lambda v: v == 0,
             doomed=_doomed_partial, settle_extra=lab.SETTLE, key="partial"),
    GoalSpec("", "after", "", _resolve, _money, lambda v: v == 0, settle_extra=lab.SETTLE, key="money"),
    GoalSpec("", "after", "", _resolve, _doubt, lambda v: v is None or v <= lab.RESOLVE,
             settle_extra=lab.SETTLE, key="doubt"),
    GoalSpec("", "after", "", _after, _completed,
             at_least(lab.COMPLETED_MIN), settle_extra=lab.SETTLE, key="completed"),
]


class TwoPhaseCommitWorld(World):
    id = "two_phase_commit"
    view = "fanout"  # opens with the fanout picture; lanes and cluster stay a key away
    stage_colours = (RED, EXTRA2, BLUE)
    legend = [(WHITE, "prepare"), (BLUE, "yes"), (GREEN, "commit"), (MUTED, "abort"), (EXTRA1, "ask"),
              (EXTRA2, "doubt", "◉"), (RED, "down", "◉"), (RED, "partial"), (LIMIT, "limit", "┄"), (DOWN_KEY, "incident", "█")]
    tables = {
        "txns": Table(sort=TX_START, times=(TX_START, TX_END)),
        "msgs": Table(sort=MSG_SENT, times=(MSG_SENT,)),
        "state": Table(sort=ST_T, times=(ST_T,)),
    }
    goals = GOALS
    chart_top = 0.0

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.victims: dict[float, int] = {}  # incident start -> the shard it hits (1..3)

    @property
    def rate(self) -> float:
        return float(self.params.get("rate", 10.0))

    # ---------------------------------------------------------------- data

    def append(self, variant: str, piece: dict) -> None:
        self.victims.update(piece.get("victims", {}))  # before the incidents' words are written
        super().append(variant, piece)

    def ingest(self, run: Run, tables, piece) -> None:
        for r in tables["txns"]:
            run.add("txns", r[TX_START])
            run.add("served" if r[TX_OK] else "failed", r[TX_CEND])
            key = ("committed", "aborted", "partial", "doubt")[r[TX_STATUS]]
            run.add(key, r[TX_END])
        for m in tables["msgs"]:
            kind = m[MSG_KIND]
            if kind in (M_YES, M_NO, M_COMMIT, M_ABORT):
                run.add(f"m{kind}", m[MSG_SENT])

    def shard_name(self, inc: Incident) -> str:
        return f"n{self.victims.get(inc.t0, 2)}"

    def incident_verb(self, inc: Incident, start: bool) -> str:
        if start:
            return self.word(inc.kind)
        return self.word({"shard_crash": "back", "coord_crash": "back", "partition": "heal"}.get(inc.kind, "calm"))

    def incident_text(self, inc: Incident, start: bool) -> str:
        key = f"{inc.kind}_{'start' if start else 'end'}"
        return self.s(key, shard=self.shard_name(inc), share=inc.severity, cause=self.cause(inc))

    def warnings(self, run: Run, inc: Incident):
        out = []
        if inc.kind == "overload":
            down = lab.downtime(inc.kind, inc.t0, inc.t1)
            out += [(down[0], self.s("warn_crash")), (down[1], self.s("coord_crash_end"))]
        rows = run.rows("txns", *_during(inc))
        partial = sum(1 for r in rows if r[TX_STATUS] == PARTIAL)
        stuck = sum(1 for r in rows if r[TX_RESOLVED] is None)
        held = [r[TX_RESOLVED] - min(p for p in r[TX_PREP] if p >= 0) for r in rows
                if r[TX_RESOLVED] is not None and any(p >= 0 for p in r[TX_PREP])]
        if held and max(held) >= 1.0:  # the price of 2PC, even done right: rows locked while in doubt
            out.append((inc.t1, self.s("warn_blocked", seconds=max(held))))
        if partial:
            out.append((inc.t1, self.s("warn_partial", n=partial)))
        if stuck:
            out.append((inc.t1, self.s("warn_stuck", n=stuck)))
        return out

    def state_at(self, variant: str, t: float) -> tuple | None:
        """The checker's last look at the shards' disks, at or before t."""
        run = self.runs.get(variant)
        if run is None:
            return None
        rows = run.rows("state", t - 1.0, t + 1e-9)
        return rows[-1] if rows else None

    def coord_down(self, variant: str, t: float) -> bool:
        st = self.state_at(variant, t)
        return st is not None and bool(st[ST_DOWN] & 1)

    def recent_partials(self, run: Run, t: float, span: float = 2.0) -> list[tuple]:
        """Transfers left partial that ended in the last `span` seconds."""
        longest = run.max_dur.get("txns", 0.0)
        return [r for r in run.rows("txns", t - span - longest, t + 1e-9)
                if r[TX_STATUS] == PARTIAL and t - span <= r[TX_END] <= t]

    # ---------------------------------------------------------------- panel

    def traffic(self, variant: str, t: float) -> Traffic:
        run = self.runs[variant]
        longest = run.max_dur.get("txns", 0.0)
        recent = [r for r in run.rows("txns", t - 10 - longest, t) if t - 10 <= r[TX_END] < t]
        partial = sum(1 for r in recent if r[TX_STATUS] == PARTIAL)
        st = self.state_at(variant, t)
        drift = st[ST_MONEY] if st else 0
        doubt = sum(st[ST_DOUBT]) if st else 0
        inc = self.incident_at(variant, t)

        def count_s(name: str):
            def fn(s: int):
                v = run.series(name, s, s + 1)[0]
                return v, "bad" if v else "ok"
            return fn

        def sample(s: int) -> tuple | None:
            rows = run.rows("state", s, s + 1)
            return rows[-1] if rows else None

        def money_s(s: int):
            got = sample(s)
            v = abs(got[ST_MONEY]) if got else 0
            return float(v), "bad" if v else "ok"

        def doubt_state(n: int, busy: bool) -> str:
            return "ok" if n == 0 else "warn" if busy else "bad"

        def doubt_s(s: int):
            got = sample(s)
            n = sum(got[ST_DOUBT]) if got else 0
            busy = any(i.t0 <= s < i.t1 for i in run.incidents)
            return float(n), doubt_state(n, busy)

        tiles = [
            Tile(self.s("tile_partial"), str(partial), "=0", "bad" if partial else "ok",
                 history(run, t, count_s("partial"))),
            Tile(self.s("tile_money"), money(drift), "=$0", "bad" if drift else "ok", history(run, t, money_s)),
            Tile(self.s("tile_doubt"), str(doubt), "→0", doubt_state(doubt, inc is not None),
                 history(run, t, doubt_s)),
        ]
        s = int(t)
        votes = [run.series(f"m{k}", s - 1, s)[0] for k in (M_YES, M_NO)]
        decided = [run.series(f"m{k}", s - 1, s)[0] for k in (M_COMMIT, M_ABORT)]
        ended = [r for r in run.rows("txns", t - 1 - longest, t) if t - 1 <= r[TX_END] < t]
        by = [sum(1 for r in ended if r[TX_STATUS] == k) for k in (COMMITTED, ABORTED, IN_DOUBT, PARTIAL)]
        bars = [
            Bar(self.s("bar_votes"), [(votes[0], BLUE), (votes[1], MUTED)]),
            Bar(self.s("bar_decided"), [(decided[0], GREEN), (decided[1], MUTED)]),
            Bar(self.s("bar_ended"), [(float(by[0]), WHITE), (float(by[1]), MUTED), (float(by[2]), EXTRA2),
                                      (float(by[3]), RED)]),
        ]
        if partial:
            headline, colour = self.s("head_partial", n=partial), RED
        elif self.coord_down(variant, t):
            headline, colour = self.s("head_down", n=doubt), RED
        elif doubt:
            headline, colour = self.s("head_doubt", n=doubt), EXTRA2
        elif inc is not None:
            headline, colour = self.s("head_failing"), EXTRA2
        else:
            headline, colour = self.s("head_ok"), MUTED
        return Traffic(tiles, bars, self.rate, self.s("limit"), headline, colour,
                       title=self.s("title"), subtitle=self.s("subtitle"), top=self.rate * 4)

    def user_stats(self, variant: str, t: float):
        return self.request_stats(self.runs[variant], "txns", TX_START, TX_CEND, TX_OK, t)

    def stacks(self, variant: str):
        run = self.runs[variant]
        return [(WHITE, run.hist.get("committed", [])), (MUTED, run.hist.get("aborted", [])),
                (EXTRA2, run.hist.get("doubt", [])), (RED, run.hist.get("partial", []))]

    def chart_limit(self):
        return self.rate, self.s("limit")

    chart_top = 20.0

    def legend_notes(self) -> list[str]:
        return [self.s("note")]


WORLD = TwoPhaseCommitWorld
