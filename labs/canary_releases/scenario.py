"""Lab canary_releases: one endless run on virtual time, handed out a minute at a time.

Users send ~200 requests/s to four endpoints (/home, /search, /cart, /pay). A router spreads them
over a fleet of 20 instances running the live build. Now and then the team ships a new build: a
release. For each release the scenario makes one `Release()` from your code and, every TICK
seconds, calls `release.decide(metrics)`; you answer with the share of traffic the new build should
get. The router sends that share of requests (at random, request by request) to instances running the
new build, and the rest to the live one. Answer 1.0 and the new build becomes the live build
everywhere (the release is done); answer 0.0 and it is rolled back (the release is over). The metrics
compare the new build (the canary) with the live one (the baseline) over the same seconds: every
request since the router last changed its split, in total and per endpoint.

Most builds are fine. Some are bad, each in its own way: a crash loop (it fails most requests), a
subtle error regression (0.3% errors become ~3%), a latency regression (a slow code path: +150-250
ms on a quarter of the requests, no errors), or a bug that only breaks /pay (5% of the traffic).
And sometimes a good build ships while a dependency flakes: errors and slow answers go up on BOTH
builds, for reasons that have nothing to do with the release.

Each release is an incident: it starts when the build is deployed, and its window closes WINDOW
seconds later. A release still ramping then is cancelled (rolled back). A bad build that reached
100% stays live until then: at the end of the window someone on call notices and rolls it back by
hand. The first release is always a latency regression at 0:20. The run never restarts: the live
build, the clock and the traffic carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, rate_at, schedule
from core.vtime import VirtualRun, now

LAB = "canary_releases"
NAMES = ("Release", "Metrics", "Counts", "fixed_canary", "z_score", "worse", "ramp")
PIECE = 60.0
DRAIN = 2.0  # simulate this far past a minute before handing it out (every request ends by then)
BATCH = 0.1  # users are generated this many seconds at a time

FLEET = 20  # instances behind the router (for the pictures: a canary of 5% is one instance)
ENDPOINTS = ("home", "search", "cart", "pay")
MIX = (0.55, 0.25, 0.15, 0.05)  # the share of the traffic each endpoint gets
PAY = ENDPOINTS.index("pay")
LATENCY = 0.05  # seconds: the median answer
SPREAD = 0.5  # log-normal sigma of the answer time (p99 ~160 ms)
BASE_ERRORS = 0.003  # errors any build has (a client hangs up, a rare bug): 0.3%
SLOW = 0.25  # seconds: an answer slower than this counts as slow (in the metrics too)
CRASH_FAST = (0.002, 0.010)  # a crash-looping instance refuses at once: a fast 502
SLOWED = 0.25  # the share of requests a latency regression slows down (one slow code path)
HICCUP_LAT = (0.2, 0.5)  # what a flaky dependency adds to a request it slows (retries inside)
HICCUP_CYCLE = 10.0  # a flaky dependency comes and goes: bad for 6 s of every 10
TICK = 5.0  # your Release.decide runs this often during a release
WINDOW = 120.0  # seconds from a deploy to the end of its release window
FIRST_VERSION = 100  # the build live at 0:00; release k ships version FIRST_VERSION + 1 + k

# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
GOOD_KINDS = ("good", "flaky")
FIRST = Planned(20.0, 20.0 + WINDOW, "latency", 0.2, "n_plus_one")
KINDS = [
    Kind("good", 0.2, median=WINDOW, shortest=WINDOW, longest=WINDOW, causes=(
        "copy_change", "dependency_bump", "refactor", "flag_cleanup")),
    Kind("flaky", 0.2, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.10, 0.20), causes=(
        "db_failover", "dns_blip", "provider_slow", "cache_restart")),
    Kind("crash", 0.15, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.5, 0.8), causes=(
        "missing_env", "bad_config", "oom_start", "schema_mismatch")),
    Kind("errors", 0.15, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.025, 0.035), causes=(
        "edge_case", "short_timeout", "retry_removed", "serializer")),
    Kind("latency", 0.15, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.15, 0.25), causes=(
        "n_plus_one", "sync_logging", "cache_key", "regex")),
    Kind("segment", 0.15, median=WINDOW, shortest=WINDOW, longest=WINDOW, severity=(0.15, 0.3), causes=(
        "currency_rounding", "coupon_parser", "tax_rule", "card_validation")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # at least this calm between two release windows: the baseline, and time to judge

# What the router did, in the `events` table (keys; the World has the words).
DEPLOY, STEP, FULL, ROLLBACK, CANCEL, MANUAL = "deploy", "step", "full", "rollback", "cancel", "manual"


def _s(key: str, **values) -> str:
    """One of the lab's STRINGS in the language in use (errors your code may see)."""
    return lab_text(LAB).STRINGS[key].format(**values)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def bad(kind: str) -> bool:
    """A build that hurts users (a flaky dependency does, but the build itself is fine)."""
    return kind not in GOOD_KINDS


@dataclass(frozen=True, slots=True)
class Build:
    version: int
    kind: str = "good"  # good, flaky (a good build), crash, errors, latency or segment
    severity: float = 0.0


class _Tally:
    """Requests, errors and slow answers of one build since the router last changed its split."""

    __slots__ = ("n", "errors", "slow")

    def __init__(self) -> None:
        self.n = self.errors = self.slow = 0

    def add(self, ok: bool, slow: bool) -> None:
        self.n += 1
        self.errors += not ok
        self.slow += slow


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.rng = random.Random(seed * 7 + 1)  # what each request does
        self.route_rng = random.Random(seed * 7 + 2)  # the router's split
        self.dep_rng = random.Random(seed * 7 + 3)  # when a dependency flakes
        self.live = Build(FIRST_VERSION)
        self.new: Build | None = None  # the build being released, if any
        self.weight = 0.0  # the share of traffic the router sends to the new build
        self.counting = False  # a release is being measured
        self.tally = self._tallies()
        self.hiccups: list[tuple[float, float, float]] = []  # (start, end, error share) of a flaky dependency
        self.planned: list[Planned] = []
        self.ids = itertools.count()
        self.requests: list[tuple] = []  # (id, start, end, ok, canary, endpoint, harmed, slow)
        self.ticks: list[tuple] = []  # (t, release, before, after, c_n, c_err, c_slow, b_n, b_err, b_slow)
        self.events: list[tuple] = []  # (t, release, version, what, weight, live version)
        self.bugs: list[BaseException] = []

    @staticmethod
    def _tallies() -> dict[tuple[int, int], _Tally]:
        """(canary 1 / baseline 0, endpoint) -> its tally; endpoint -1 is every endpoint."""
        return {(c, e): _Tally() for c in (0, 1) for e in range(-1, len(ENDPOINTS))}

    # ---------------------------------------------------------------- requests

    def hiccup(self, t: float) -> float:
        """The share of requests a flaky dependency fails at t (0 when it is fine)."""
        for a, b, share in self.hiccups[-2:]:
            if a <= t < b:
                return share if (t - a) % HICCUP_CYCLE < 6.0 else share * 0.1
        return 0.0

    def request(self, rid: int, t: float, e: int) -> None:
        rng = self.rng
        canary = self.new is not None and self.weight > 0.0 and self.route_rng.random() < self.weight
        build = self.new if canary else self.live
        latency = rng.lognormvariate(math.log(LATENCY), SPREAD)
        ok = rng.random() >= BASE_ERRORS
        harmed = False
        flaky = self.hiccup(t)
        if flaky:  # a dependency both builds call: it fails or slows requests whatever the build
            if rng.random() < flaky:
                ok = False
            elif rng.random() < 2 * flaky:
                latency += rng.uniform(*HICCUP_LAT)
        kind, sev = build.kind, build.severity
        if kind == "crash" and rng.random() < sev:  # the instance is restarting: refused at once
            harmed, ok, latency = ok, False, rng.uniform(*CRASH_FAST)
        elif kind == "errors" and rng.random() < sev:
            harmed, ok = ok, False
        elif kind == "segment" and e == PAY and rng.random() < sev:
            harmed, ok = ok, False
        elif kind == "latency" and rng.random() < SLOWED:
            harmed = True
            latency += sev * rng.uniform(0.8, 1.2)
        slow = ok and latency > SLOW
        self.requests.append((rid, t, t + latency, ok, canary, e, harmed, slow))
        if self.counting:
            c = int(canary)
            self.tally[(c, -1)].add(ok, slow)
            self.tally[(c, e)].add(ok, slow)

    async def traffic(self) -> None:
        """Users arrive as a Poisson process whose rate drifts, BATCH seconds at a time."""
        rng = random.Random(self.seed * 7)
        cum = list(itertools.accumulate(MIX))
        t = 0.0
        while True:
            end = now() + BATCH
            rate = rate_at(self.rate, now(), self.seed)
            while True:
                t += rng.expovariate(rate)
                if t >= end:
                    t = end  # memoryless: start the next batch at its edge
                    break
                u = rng.random()
                e = next(i for i, c in enumerate(cum) if u < c or i == len(cum) - 1)
                try:
                    self.request(next(self.ids), round(t, 4), e)
                except Exception as exc:  # a bug in the scenario must not hang the run
                    self.bugs.append(exc)
                    return
            await asyncio.sleep(end - now())

    # ---------------------------------------------------------------- releases

    def counts(self, canary: int, e: int):
        x = self.tally[(canary, e)]
        return self.code.Counts(requests=x.n, errors=x.errors, slow=x.slow)

    def metrics(self, t: float, since: float, step_since: float):
        endpoints = {name: (self.counts(1, e), self.counts(0, e)) for e, name in enumerate(ENDPOINTS)}
        return self.code.Metrics(t=t, since=since, weight=self.weight, step_age=round(t - step_since, 3),
                                 canary=self.counts(1, -1), baseline=self.counts(0, -1), endpoints=endpoints)

    def event(self, k: int, what: str, weight: float) -> None:
        version = self.new.version if self.new is not None else self.live.version
        self.events.append((round(now(), 3), k, version, what, weight, self.live.version))

    def set_weight(self, w: float) -> None:
        self.weight = w
        self.tally = self._tallies()  # each split is measured on its own

    async def release(self, k: int, inc: Planned) -> None:
        """Ship build k: ask your Release every TICK s until it says 1.0 (done) or 0.0 (rolled back)."""
        before = self.live
        self.new = Build(FIRST_VERSION + 1 + k, inc.kind, inc.severity)
        self.set_weight(0.0)
        self.counting = True
        policy = self.code.Release()
        since = step_since = now()
        self.event(k, DEPLOY, 0.0)
        outcome, last = CANCEL, 0.0
        while now() < inc.t1 - 1e-9:
            t = now()
            try:
                w = policy.decide(self.metrics(t, since, step_since))
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return
            if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0.0 <= w <= 1.0:
                self.bugs.append(TypeError(_s("bad_weight", value=repr(w))))
                return
            w = float(w)
            old = self.weight
            self.ticks.append((round(t, 3), k, old, w, *(getattr(x, f) for x in (self.counts(1, -1), self.counts(0, -1))
                                                          for f in ("requests", "errors", "slow"))))
            if w >= 1.0:
                self.live, outcome, last = self.new, FULL, 1.0
                break
            if w <= 0.0:
                outcome, last = ROLLBACK, old
                break
            if w != old:
                self.set_weight(w)
                step_since = t
                self.event(k, STEP, w)
            await asyncio.sleep(TICK)
        if outcome == CANCEL:
            last = self.weight
        self.set_weight(0.0)
        self.counting = False
        self.event(k, outcome, last)  # full, rollback (at the share it had), or cancel (still ramping at the end)
        self.new = None
        await asyncio.sleep(max(0.0, inc.t1 - now()))
        if bad(self.live.kind) and self.live.version == FIRST_VERSION + 1 + k:
            self.live = before  # on call notices and rolls the bad build back by hand
            self.event(k, MANUAL, 0.0)

    async def chaos(self) -> None:
        for k, inc in enumerate(incidents(self.seed)):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "flaky":  # the dependency flakes a few seconds into the release
                a = inc.t0 + self.dep_rng.uniform(5.0, 20.0)
                self.hiccups.append((a, a + self.dep_rng.uniform(45.0, 75.0), inc.severity))
            await self.release(k, inc)
            if self.bugs:
                return

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 200.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for task in (s.traffic(), s.chaos()):
        sim.spawn(task)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "ticks": s.take(s.ticks, 0, a, b),
                    "events": s.take(s.events, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 200.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
