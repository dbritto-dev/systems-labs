import itertools
import math

import pytest

from core.contract import import_module, load
from core.testing import build_world, variant, your_code
from labs.canary_releases import lab, scenario

code = load("canary_releases", variant(), scenario.NAMES)
consts = import_module("canary_releases", variant())  # STEPS, MIN_BAD, Z_LIMIT, ...
ref = load("canary_releases", "reference", scenario.NAMES)
Counts, Metrics = ref.Counts, ref.Metrics


def z(bad_a, n_a, bad_b, n_b):
    if not n_a or not n_b:
        return 0.0
    p = (bad_a + bad_b) / (n_a + n_b)
    se = math.sqrt(p * (1 - p) * (1 / n_a + 1 / n_b))
    return 0.0 if se == 0 else (bad_a / n_a - bad_b / n_b) / se


class AllAtOnce:  # stage 0: every user gets the new build at once
    def decide(self, m):
        return 1.0


class AllAtOnceInt(AllAtOnce):  # stage 0, an int works too
    def decide(self, m):
        return 1


class FixedCanary:  # stage 1: 5%, roll back above 5% errors, everywhere after 60 s
    share, bake, limit = 0.05, 60.0, 0.05

    def decide(self, m):
        c = m.canary
        if c.requests and c.errors / c.requests > self.limit:
            return 0.0
        return 1.0 if m.t - m.since >= self.bake else self.share


class FixedCanaryTight(FixedCanary):  # stage 1 with other numbers: still blind to latency
    share, bake, limit = 0.10, 40.0, 0.03


class Staged:  # stage 2: the baseline, errors and slow, per endpoint, a minimum count, steps
    steps, step_bake, min_samples, min_bad, z_limit = (0.05, 0.25, 0.5, 1.0), 20.0, 200, 5, 4.0
    metrics = ("errors", "slow")
    per_endpoint = True

    def worse(self, c, b):
        return any(getattr(c, k) >= self.min_bad
                   and z(getattr(c, k), c.requests, getattr(b, k), b.requests) > self.z_limit for k in self.metrics)

    def decide(self, m):
        pairs = [(m.canary, m.baseline)] + (list(m.endpoints.values()) if self.per_endpoint else [])
        if any(self.worse(c, b) for c, b in pairs):
            return 0.0
        if m.weight == 0.0:
            return self.steps[0]
        if m.step_age >= self.step_bake and m.canary.requests >= self.min_samples:
            return min(s for s in self.steps if s > m.weight)
        return m.weight


class ErrorsOnly(Staged):  # stage 2 that compares errors but not latency: the slow build goes live
    metrics = ("errors",)


class TotalOnly(Staged):  # stage 2 without the per-endpoint check: the /pay bug is diluted in the total
    per_endpoint = False


class LooseZ(Staged):  # stage 2 with a bar of 3 standard errors: 10 tests every 5 s cross it by chance
    z_limit = 3.0


class NoMinimum(Staged):  # stage 2 that blames the canary for one bad answer
    min_bad, z_limit = 1, 2.0


class Slow(Staged):  # stage 2 that bakes each step 60 s: good builds take too long
    step_bake = 60.0


def as_module(policy):
    return type(policy.__name__.upper(), (), {"Release": policy, "Metrics": Metrics, "Counts": Counts,
                                               "fixed_canary": None, "z_score": None, "worse": None, "ramp": None})


ALL, ALL_INT, FIXED, FIXED_TIGHT, STAGED, ERRORS_ONLY, TOTAL_ONLY, LOOSE_Z, NO_MIN, SLOW = (as_module(p) for p in (
    AllAtOnce, AllAtOnceInt, FixedCanary, FixedCanaryTight, Staged, ErrorsOnly, TotalOnly, LooseZ, NoMinimum, Slow))
FIRST_SETTLED = 3  # minutes until the first release (0:20-2:20) is judged


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def values(world, v, inc=0):
    return {g.key: r.value for g, r in zip(world.goals, world.runs[v].settled[inc])}


def outcomes(world, v):
    """How each release ended: full, rollback or cancel."""
    ends = {}
    for e in world.runs[v].data["events"]:  # (t, release, version, what, weight, live)
        if e[3] in (scenario.FULL, scenario.ROLLBACK, scenario.CANCEL):
            ends.setdefault(e[1], e[3])
    return [ends[k] for k in sorted(ends)]


def release(world, v, k):
    inc = world.runs[v].incidents[k]
    return inc.kind, outcomes(world, v)[k], statuses(world, v)[k]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("module, stage", [
    (ALL, 0),  # everywhere at once
    (ALL_INT, 0),  # the same, with an int
    (FIXED, 1),  # a 5% canary with fixed rules
    (FIXED_TIGHT, 1),  # other numbers: still blind to latency
    (ERRORS_ONLY, 1),  # compared with the baseline, but on errors only
    (STAGED, 2),  # staged, compared with the baseline on errors and latency
])
def test_each_stage_is_judged_from_what_the_run_did(module, stage, seed):
    world = build_world("canary_releases", module, FIRST_SETTLED, seed=seed)
    baseline, hurt, full, alarms, rollout = statuses(world, module)[0]
    assert world.stage_index(module) == stage
    assert baseline and alarms and rollout  # the first build is a bad one: nothing to time, no false alarm
    assert full == hurt == (stage == 2)  # the slow build goes live, and hurts a quarter of everyone's requests
    assert outcomes(world, module)[0] == (scenario.ROLLBACK if stage == 2 else scenario.FULL)


def test_everywhere_at_once_hurts_every_user_until_someone_rolls_back_by_hand():
    world = build_world("canary_releases", ALL, FIRST_SETTLED)
    assert float(values(world, ALL)["hurt"].strip("%")) > 20  # a quarter of the requests, for 2 minutes
    run = world.runs[ALL]
    whats = [e[3] for e in run.data["events"] if e[1] == 0]
    assert whats == [scenario.DEPLOY, scenario.FULL, scenario.MANUAL]
    rows = run.rows("requests", 145.0, 175.0)
    assert not any(r[6] for r in rows)  # after the manual rollback the old build serves again


def test_a_fixed_canary_catches_a_crash_loop_in_seconds():
    """Seed 8 ships a crash loop at 3:45: a fixed error limit rolls it back from 5% at once."""
    world = build_world("canary_releases", FIXED, 7, seed=8)
    kind, end, ok = release(world, FIXED, 1)
    assert kind == "crash" and end == scenario.ROLLBACK and all(ok)
    rolled = next(e for e in world.runs[FIXED].data["events"] if e[1] == 1 and e[3] == scenario.ROLLBACK)
    assert rolled[0] - world.runs[FIXED].incidents[1].t0 <= scenario.TICK + 1e-6 and rolled[4] == 0.05


def test_a_fixed_canary_rolls_back_a_good_build_when_a_dependency_flakes():
    """Seed 6 ships a good build at 2:58 while the database fails over: both builds fail more, the fixed
    limit blames the new one. The staged canary, compared with the baseline, ships it."""
    fixed, staged = (build_world("canary_releases", m, 6, seed=6) for m in (FIXED, STAGED))
    kind, end, ok = release(fixed, FIXED, 1)
    assert kind == "flaky" and end == scenario.ROLLBACK and not ok[3]  # a false alarm
    kind, end, ok = release(staged, STAGED, 1)
    assert end == scenario.FULL and all(ok)


def test_without_the_per_endpoint_check_the_pay_bug_goes_live():
    """Seed 1 ships a bug that breaks 30% of /pay (5% of the traffic) at 5:35: in the total it is +1.5%
    errors, under the bar until 100%."""
    total, staged = (build_world("canary_releases", m, 8, seed=1) for m in (TOTAL_ONLY, STAGED))
    kind, end, ok = release(total, TOTAL_ONLY, 2)
    assert kind == "segment" and end == scenario.FULL and not ok[2]
    kind, end, ok = release(staged, STAGED, 2)
    assert end == scenario.ROLLBACK and all(ok)


def test_a_loose_bar_or_no_minimum_count_rolls_back_good_builds():
    """You test 10 things every 5 s: at 3 standard errors one crosses by chance now and then (seed 9's
    flaky release at 3:32); with no minimum count one unlucky error does it (seed 21's good build)."""
    loose = build_world("canary_releases", LOOSE_Z, 6, seed=9)
    kind, end, ok = release(loose, LOOSE_Z, 1)
    assert kind == "flaky" and end == scenario.ROLLBACK and not ok[3]
    assert release(build_world("canary_releases", STAGED, 6, seed=9), STAGED, 1)[1] == scenario.FULL
    eager = build_world("canary_releases", NO_MIN, 6, seed=21)
    kind, end, ok = release(eager, NO_MIN, 1)
    assert kind == "good" and end == scenario.ROLLBACK and not ok[3]


def test_steps_that_bake_too_long_miss_the_rollout_bound():
    world = build_world("canary_releases", SLOW, 6, seed=1)
    kind, end, ok = release(world, SLOW, 1)
    assert kind == "good" and not ok[4]  # 5% for 60 s, 25% for 60 s: past 90 s


def test_reference_passes_every_goal():
    for seed in (1, 2, 3, 6):
        world = build_world("canary_releases", "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 2
        assert all(all(r) for r in results), (seed, results)
        assert world.stage_index("reference") == 2  # Staged canary


def test_one_run_never_restarts_and_releases_come_at_random():
    pieces = list(itertools.islice(scenario.stream("reference"), 4))
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)
    first = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 140.0, "latency") for i in first)
    later = list(itertools.islice(scenario.incidents(5), 60))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET
    assert {i.kind for i in later} == {"good", "flaky", "crash", "errors", "latency", "segment"}
    assert all(i.cause and abs(i.t1 - i.t0 - scenario.WINDOW) < 0.11 for i in later)


def test_the_router_splits_the_traffic_as_asked():
    world = build_world("canary_releases", STAGED, 5, seed=1)
    run = world.runs[STAGED]
    for a, b, share in ((190.0, 205.0, 0.05), (212.0, 225.0, 0.25), (232.0, 245.0, 0.5)):  # seed 1's good build
        rows = run.rows("requests", a, b)
        assert abs(sum(r[4] for r in rows) / len(rows) - share) < 0.05, (a, share)


def test_each_split_is_measured_on_its_own():
    seen = []

    class Spy(Staged):
        def decide(self, m):
            seen.append(m)
            return super().decide(m)

    spy = as_module(Spy)
    build_world("canary_releases", spy, 5, seed=1)
    good = [m for m in seen if 183.0 < m.since < 184.0]
    assert good[0].weight == 0.0 and good[0].canary.requests == 0
    for prev, m in zip(good, good[1:]):
        if m.weight != prev.weight and prev.weight:  # counted afresh since the split changed
            assert m.step_age == pytest.approx(scenario.TICK)
            assert m.canary.requests + m.baseline.requests < (prev.canary.requests + prev.baseline.requests) / 2
    assert set(good[-1].endpoints) == set(scenario.ENDPOINTS)
    assert sum(c.requests for c, _ in good[-1].endpoints.values()) == good[-1].canary.requests


def test_totals_survive_forgetting_old_minutes():
    world = build_world("canary_releases", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    asked = sum(len(p["tables"]["requests"]) for p in itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ask", 1e9) == asked
    assert world.stage_index("reference") == 2  # still judged once the first release's rows are gone


@pytest.mark.parametrize("answer", [1.5, -0.1, "full", None, True])
def test_a_bad_answer_names_the_problem(answer):
    class Bad(AllAtOnce):
        def decide(self, m):
            return answer

    with pytest.raises(TypeError, match="decide"):
        next(scenario.stream(as_module(Bad)))


def test_both_pictures():
    from live.views import adapter_for, set_view, views_for

    world = build_world("canary_releases", "reference", 4, seed=1)
    assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
    lane = adapter_for(world).frame("reference", 215.0, 100)  # seed 1's good build, on 25%
    assert lane.users and lane.flights and lane.state[0] and 0 < lane.fill < 1
    assert any(big for *_, big in lane.flights)  # the canary's requests stand out
    set_view(world, "cluster")
    frame = adapter_for(world).frame("reference", 215.0)
    assert len(frame.nodes) == scenario.FLEET and frame.flights
    assert len(set(frame.nodes)) == 2 and frame.nodes.count(frame.nodes[0]) == 5  # 25% = 5 of 20 instances


# ------------------------------------------------------------- your code


def metrics(**kw):
    base = dict(t=100.0, since=80.0, weight=0.05, step_age=20.0, canary=code.Counts(200, 0, 0),
                baseline=code.Counts(3800, 11, 8), endpoints={})
    return code.Metrics(**{**base, **kw})


@your_code(1, "fixed_canary: CANARY, 0.0 above ERROR_LIMIT, 1.0 after BAKE")
def test_stage1_fixed_canary():
    assert code.fixed_canary(metrics(t=80.0, weight=0.0, canary=code.Counts(0, 0, 0))) == consts.CANARY
    assert code.fixed_canary(metrics(t=100.0)) == consts.CANARY
    errors = int(200 * consts.ERROR_LIMIT) + 1
    assert code.fixed_canary(metrics(canary=code.Counts(200, errors, 0))) == 0.0
    assert code.fixed_canary(metrics(t=80.0 + consts.BAKE)) == 1.0
    assert code.fixed_canary(metrics(canary=code.Counts(200, 0, 200))) == consts.CANARY  # blind to latency


@your_code(1, "the router splits the traffic on the first release")
def test_stage1_a_canary():
    world = build_world("canary_releases", variant(), FIRST_SETTLED)
    assert world.stage_index(variant()) >= 1


@your_code(2, "z_score: a two-proportion z-test")
def test_stage2_z_score():
    assert code.z_score(30, 1000, 30, 1000) == 0.0
    assert code.z_score(30, 1000, 3, 1000) == pytest.approx(4.74, abs=0.01)
    assert code.z_score(3, 1000, 30, 1000) == pytest.approx(-4.74, abs=0.01)  # better, not worse
    assert code.z_score(0, 100, 0, 1900) == 0.0 and code.z_score(5, 0, 3, 100) == 0.0


@your_code(2, "worse: errors or slow, at least MIN_BAD, z above Z_LIMIT")
def test_stage2_worse():
    base = code.Counts(3800, 11, 8)
    assert code.worse(code.Counts(200, 20, 0), base)  # errors
    assert code.worse(code.Counts(200, 0, 40), base)  # slow answers
    assert not code.worse(code.Counts(200, 1, 0), base)  # one unlucky error: under MIN_BAD
    assert not code.worse(code.Counts(200, 16, 0), code.Counts(3800, 300, 0))  # both 8%: a flaky dependency
    assert not code.worse(code.Counts(0, 0, 0), base)


@your_code(2, "ramp: STEPS one at a time after STEP_BAKE and MIN_SAMPLES; 0.0 when worse, also per endpoint")
def test_stage2_ramp():
    steps = consts.STEPS
    assert code.ramp(metrics(weight=0.0, step_age=0.0, canary=code.Counts(0, 0, 0))) == steps[0]
    assert code.ramp(metrics(step_age=consts.STEP_BAKE - 5)) == steps[0]  # not baked yet
    assert code.ramp(metrics(canary=code.Counts(consts.MIN_SAMPLES - 1, 0, 0))) == steps[0]  # not enough samples
    assert code.ramp(metrics()) == steps[1]
    assert code.ramp(metrics(weight=steps[-2], canary=code.Counts(2000, 6, 4), baseline=code.Counts(2000, 6, 4))) == 1.0
    assert code.ramp(metrics(canary=code.Counts(200, 0, 50))) == 0.0  # slow
    pay = (code.Counts(10, 5, 0), code.Counts(190, 2, 0))  # diluted in the total, plain on /pay
    total = dict(canary=code.Counts(200, 5, 0), baseline=code.Counts(3800, 40, 8))
    assert code.ramp(metrics(**total)) == steps[1]
    assert code.ramp(metrics(**total, endpoints={"pay": pay})) == 0.0


@your_code(2, "every goal passes: the slow build undone on the canary")
def test_stage2_all_goals_pass():
    world = build_world("canary_releases", variant(), FIRST_SETTLED)
    assert statuses(world, variant())[0] == [True] * 5
    assert world.stage_index(variant()) == 2
