import itertools
import math
import random
from collections import deque

import pytest

from core.contract import import_module, load
from core.testing import build_world, starting_code, variant, your_code
from labs.autoscaling import lab, scenario

code = load("autoscaling", variant(), scenario.NAMES)
consts = import_module("autoscaling", variant())  # MIN_INSTANCES, STABILISE, ...
Metrics = load("autoscaling", "reference", scenario.NAMES).Metrics


class Fixed:  # stage 0: keep the fleet you have
    def desired(self, m):
        return m.instances


class FixedAtTwelve(Fixed):  # stage 0, a fleet set by hand
    def desired(self, m):
        return 12


class CpuRule(Fixed):  # stage 1: +1 above 70% CPU, -1 below 30%
    high, low = 0.70, 0.30

    def desired(self, m):
        return m.instances + 1 if m.cpu > self.high else m.instances - 1 if m.cpu < self.low else m.instances


class CpuRuleTighter(CpuRule):  # stage 1 with other thresholds: still one instance per tick
    high, low = 0.60, 0.20


class Tracking:  # stage 2: requests/s per instance, a stabilisation window for scale-in
    window = 40.0

    def __init__(self):
        self.wants = deque()

    def need(self, m):
        return max(2, math.ceil(m.rps / lab.TARGET_RPS))

    def desired(self, m):
        self.wants.append((m.t, self.need(m)))
        while self.wants[0][0] <= m.t - self.window:
            self.wants.popleft()
        return max(w for _, w in self.wants)


class NoStabilisation(Tracking):  # stage 2 without the window: every dip removes instances
    window = 1.0


class NoWarmup(Tracking):  # stage 2 that orders again the instances still booting: overshoot
    def need(self, m):
        return m.instances + super().need(m) - m.serving


def as_module(policy):
    return type(policy.__name__.upper(), (), {"Autoscaler": policy, "Metrics": Metrics,
                                               "cpu_step": None, "target_tracking": None})


FIXED, FIXED12, CPU, CPU_TIGHT, TRACKING, NO_STAB, NO_WARM = (as_module(p) for p in (
    Fixed, FixedAtTwelve, CpuRule, CpuRuleTighter, Tracking, NoStabilisation, NoWarmup))
FIRST_SETTLED = 4  # minutes until the first incident (0:20-2:00, then 60 s after) is judged


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def values(world, v, inc=0):
    return {g.key: r.value for g, r in zip(world.goals, world.runs[v].settled[inc])}


def ticks(world, v):
    return world.runs[v].rows("ticks", 0, 1e9)


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("module, stage", [
    (FIXED, 0),  # keep the fleet
    (FIXED12, 0),  # a fixed fleet of 12
    (CPU, 1),  # CPU thresholds, one at a time
    (CPU_TIGHT, 1),  # other thresholds: still behind the surge
    (TRACKING, 2),  # target tracking with a stabilisation window
])
def test_each_stage_is_judged_from_what_the_run_did(module, stage, seed):
    world = build_world("autoscaling", module, FIRST_SETTLED, seed=seed)
    baseline, served, p99, headroom, flaps, cost = statuses(world, module)[0]
    assert world.stage_index(module) == stage
    assert baseline and flaps  # nobody flaps on the way up
    assert headroom == (stage == 2)  # a fixed fleet, or one more per tick, ends the surge short of room
    if stage == 0:
        assert not served  # users time out
    if stage == 2:
        assert served and p99 and cost


def test_a_fixed_fleet_overloads_on_the_surge_and_idles_at_night():
    world = build_world("autoscaling", FIXED, 7)
    run = world.runs[FIXED]
    inc = run.incidents[0]
    rows = run.rows("requests", inc.t0, inc.t1)
    assert sum(not r[3] for r in rows) / len(rows) > 0.1  # users time out
    night = run.rows("samples", 350, 370)  # the quietest moment of the day: 6:00
    assert sum(s[2] for s in night) / sum(s[1] for s in night) > 2.5  # over 60% of the fleet idles


def test_cpu_thresholds_add_one_instance_per_tick_and_fall_behind():
    world = build_world("autoscaling", CPU, FIRST_SETTLED)
    steps = [r[2] - r[1] for r in ticks(world, CPU)]
    assert max(steps) == 1 and min(steps) >= -1
    assert float(values(world, CPU)["headroom"].strip("%")) < 100 * lab.HEADROOM_MIN


def test_cpu_is_a_misleading_signal_when_a_batch_job_runs():
    """Seed 4 has a noisy batch job at 3:14 while the traffic falls: CPU rules add instances for it (and
    never shrink the fleet the surge left), target tracking keeps shrinking it."""
    cpu, track = (build_world("autoscaling", m, 6, seed=4) for m in (CPU, TRACKING))
    inc = cpu.runs[CPU].incidents[1]
    assert inc.kind == "noisy"
    assert not statuses(cpu, CPU)[1][5] and statuses(track, TRACKING)[1][5]  # cost

    def added(world, module):
        return sum(r[2] - r[1] for r in ticks(world, module) if inc.t0 <= r[0] < inc.t1 and r[2] > r[1])

    assert added(cpu, CPU) >= 2 and added(track, TRACKING) == 0


def test_without_a_stabilisation_window_the_fleet_flaps():
    from live.worlds.autoscaling import flaps

    def total(module):
        return sum(flaps(ticks(w, module), 0.0) for w in (build_world("autoscaling", module, 5, seed=s)
                                                         for s in (1, 2, 3)))

    assert total(NO_STAB) >= 3 * total(TRACKING) + 6


def test_without_warm_up_accounting_the_fleet_overshoots():
    """Ordering again the instances still booting buys a bigger fleet for the same surge."""
    for seed in (1, 2, 3):
        good, over = (build_world("autoscaling", m, FIRST_SETTLED, seed=seed) for m in (TRACKING, NO_WARM))
        cost = [float(values(w, m)["cost"].strip("%")) for w, m in ((good, TRACKING), (over, NO_WARM))]
        assert cost[1] > cost[0] + 10, cost
        assert statuses(good, TRACKING)[0][5]


def test_reference_passes_every_goal():
    for seed in (1, 2, 3):
        world = build_world("autoscaling", "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 2
        assert all(all(r) for r in results), (seed, results)
        assert world.stage_index("reference") == 2  # Target tracking


def test_one_run_never_restarts_and_incidents_come_at_random():
    pieces = list(itertools.islice(scenario.stream("reference"), 4))
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)
    first = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 120.0, "surge") for i in first)
    later = list(itertools.islice(scenario.incidents(5), 40))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET and {i.kind for i in later} == {"surge", "drop", "noisy", "cold"}
    assert all(i.cause for i in later)


def test_traffic_follows_the_day_and_incidents():
    surge = scenario.Planned(100.0, 200.0, "surge", 2.0, "tv_ad")
    assert scenario.multiplier(surge, 99.0) == 1.0 and scenario.multiplier(surge, 130.0) == pytest.approx(1.5)
    assert scenario.multiplier(surge, 190.0) == 2.0 and scenario.multiplier(surge, 230.0) == 1.0
    drop = scenario.Planned(100.0, 200.0, "drop", 0.5, "region_failover")
    assert scenario.multiplier(drop, 150.0) == 0.5 and 0.5 < scenario.multiplier(drop, 220.0) < 1.0
    assert scenario.day(60.0) == pytest.approx(1.4) and scenario.day(360.0) == pytest.approx(0.6)


def test_a_new_instance_boots_then_warms_up():
    inst = scenario.Instance(0, 0, 10.0, 40.0, random.Random(1))
    assert inst.state(39.9) == scenario.BOOTING and inst.state(40.0) == scenario.WARMING
    assert inst.slowness(40.0) == scenario.COLD and 1.0 < inst.slowness(50.0) < scenario.COLD
    assert inst.state(60.0) == scenario.WARM_STATE and inst.slowness(60.0) == 1.0


def test_totals_survive_forgetting_old_minutes():
    world = build_world("autoscaling", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    asked = sum(len(p["tables"]["requests"]) for p in itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ask", 1e9) == asked
    assert world.stage_index("reference") == 2  # still judged once the first incident's rows are gone


def test_the_fleet_stays_between_its_bounds():
    class Greedy(Fixed):
        def desired(self, m):
            return 1000 if m.t < 30 else -5

    greedy = as_module(Greedy)
    world = build_world("autoscaling", greedy, 1)
    sizes = [r[2] for r in ticks(world, greedy)]
    assert max(sizes) == scenario.MAX_INSTANCES and min(sizes) == scenario.MIN_INSTANCES


def test_a_bad_desired_names_the_problem():
    class Bad(Fixed):
        def desired(self, m):
            return m.rps / 10  # a float, not a number of instances

    with pytest.raises(TypeError, match="desired"):
        next(scenario.stream(as_module(Bad)))


def test_both_pictures():
    from live.views import adapter_for, set_view, views_for

    world = build_world("autoscaling", "reference", 1)
    assert views_for(world) == ["lanes", "cluster", "relay"] and world.view == "lanes"  # lanes opens first
    lane = adapter_for(world).frame("reference", 50.0, 100)
    assert lane.users and lane.flights and lane.state[0] and 0 < lane.fill < 1
    set_view(world, "cluster")
    frame = adapter_for(world).frame("reference", 50.0)
    assert len(frame.nodes) == scenario.MAX_INSTANCES and frame.flights
    assert len(set(frame.nodes)) >= 3  # empty slots, booting instances, warm ones


@starting_code
def test_the_relay_picture_shows_the_fleet_falling_behind():
    from live.canvas import RED
    from live.views import adapter_for, set_view

    def relay(v):
        world = build_world("autoscaling", v, 2)
        set_view(world, "relay")
        return adapter_for(world).frame(v, 85.0, 100)  # the surge, near its top

    given, solved = relay("main"), relay("reference")
    assert given.users and given.flights and given.hops and given.relay.label[0] and given.state[0]
    # a fixed fleet: the traffic is past what it can do, the balancer red, requests time out in red
    assert given.relay.gauge == RED and given.closed and any(c == RED for _, c, _ in given.hops)
    # one that follows the traffic: the load under what it can do, more of the instances it needs serving
    assert solved.relay.gauge != RED and not solved.closed and solved.fill > given.fill


# ------------------------------------------------------------- your code


@your_code(1, "cpu_step: +1 above SCALE_OUT_CPU, -1 below SCALE_IN_CPU, else the same")
def test_stage1_cpu_step():
    assert code.cpu_step(0.85, 10) == 11
    assert code.cpu_step(0.10, 10) == 9
    assert code.cpu_step(0.50, 10) == 10
    assert code.cpu_step(0.70, 4) == 4 and code.cpu_step(0.30, 4) == 4  # the thresholds themselves: hold


@your_code(1, "the fleet grows during the surge")
def test_stage1_the_fleet_grows():
    world = build_world("autoscaling", variant(), FIRST_SETTLED)
    assert world.stage_index(variant()) >= 1


def metrics(**kw):
    base = dict(t=100.0, instances=10, booting=0, warming=0, rps=100.0, cpu=0.5, in_flight=1.0)
    return code.Metrics(**{**base, **kw})


@your_code(2, "target_tracking: ceil(rps / TARGET_RPS), at least MIN_INSTANCES, booting ones counted")
def test_stage2_target_tracking():
    assert code.target_tracking(metrics(rps=100.0)) == 10
    assert code.target_tracking(metrics(rps=101.0)) == 11
    assert code.target_tracking(metrics(rps=3.0)) == consts.MIN_INSTANCES
    assert code.target_tracking(metrics(rps=250.0, instances=25, booting=10)) == 25  # do not order them again
    assert code.target_tracking(metrics(rps=100.0, cpu=0.99)) == 10  # CPU does not move it


@your_code(2, "stabilised: scale out at once, scale in only after STABILISE seconds")
def test_stage2_stabilised():
    a = code.Autoscaler()
    assert a.stabilised(0.0, 10) == 10
    assert a.stabilised(10.0, 14) == 14  # up: at once
    assert a.stabilised(20.0, 8) == 14  # down: not yet
    assert a.stabilised(10.0 + consts.STABILISE - 1, 8) == 14
    assert a.stabilised(10.0 + consts.STABILISE + 1, 8) == 8  # every recommendation of the window agrees


@your_code(2, "every goal passes: the surge served, headroom, no flapping, cost near the ideal")
def test_stage2_all_goals_pass():
    world = build_world("autoscaling", variant(), FIRST_SETTLED)
    assert statuses(world, variant())[0] == [True] * 6
    assert world.stage_index(variant()) == 2
