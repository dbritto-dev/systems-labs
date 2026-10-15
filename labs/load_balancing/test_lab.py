import itertools
import random
from collections import Counter

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.load_balancing import scenario

code = load("load_balancing", variant(), scenario.NAMES)


class RoundRobin:  # stage 0: the next server in turn, whatever its load
    def __init__(self, servers, rng):
        self.servers, self.rng, self.next = servers, rng, 0

    def pick(self, loads):
        i, self.next = self.next, (self.next + 1) % self.servers
        return i


class LeastOutstanding(RoundRobin):  # stage 1: the least loaded server in the (stale) report
    def pick(self, loads):
        return min(range(self.servers), key=loads.__getitem__)


class LeastOutstandingAnyTie(RoundRobin):  # stage 1, ties broken at random: it still herds
    def pick(self, loads):
        low = min(loads)
        return self.rng.choice([i for i, n in enumerate(loads) if n == low])


class TwoChoices(RoundRobin):  # stage 2, drawn with replacement: the same server twice now and then
    def pick(self, loads):
        a, b = self.rng.randrange(self.servers), self.rng.randrange(self.servers)
        return a if loads[a] < loads[b] else b


def as_module(balancer):
    return type(balancer.__name__.upper(), (), {"Balancer": balancer})


ROUND_ROBIN, LEAST, LEAST_ANY, TWO = (as_module(b) for b in (RoundRobin, LeastOutstanding,
                                                             LeastOutstandingAnyTie, TwoChoices))


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("module, stage", [
    (ROUND_ROBIN, 0),  # Round robin
    (LEAST, 1),  # Least outstanding
    (LEAST_ANY, 1),  # Least outstanding, any tie
    (TWO, 2),  # Power of two choices
])
def test_each_stage_is_judged_from_what_the_run_did(module, stage, seed):
    world = build_world("load_balancing", module, 1, seed=seed)
    baseline, share, p99, served, _ = statuses(world, module)[0]
    assert world.stage_index(module) == stage
    assert baseline
    assert share == (stage >= 1)  # round robin gives the slow server its full 1 in 8
    assert (p99 and served) == (stage >= 2)  # least outstanding herds onto it: timeouts


def test_round_robin_feeds_the_slow_server_its_full_share():
    world = build_world("load_balancing", ROUND_ROBIN, 1)
    run = world.runs[ROUND_ROBIN]
    inc = run.incidents[0]
    rows = run.rows("requests", inc.t0, inc.t1)
    assert sum(r[6] for r in rows) / len(rows) == pytest.approx(1 / 8, abs=0.005)
    assert sum(not r[3] for r in rows) / len(rows) > 0.05  # its users time out


def test_least_outstanding_herds_on_a_stale_report():
    """Between two reports a least-loaded balancer sends (almost) everything to one server; two choices
    spread the same traffic."""

    def worst_herd(module):
        world = build_world("load_balancing", module, 1)
        run = world.runs[module]
        return sorted(max(world.herding(run, t)) for t in range(2, 19))[8]  # the median, before the incident

    assert worst_herd(LEAST) > 0.8
    assert worst_herd(TWO) < 0.5


def test_reference_passes_every_goal():
    for seed in (1, 2, 3):
        world = build_world("load_balancing", "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 5
        assert all(all(r) for r in results), (seed, results)
        assert world.stage_index("reference") == 2  # Power of two choices


def test_one_run_never_restarts_and_incidents_come_at_random():
    pieces = list(itertools.islice(scenario.stream("reference"), 4))
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)
    first = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 32.0, "slow") for i in first)
    assert all(next(scenario.sick_servers(s)) == scenario.FIRST_SERVER for s in (1, 2, 9))
    later = list(itertools.islice(scenario.incidents(5), 30))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET and {i.kind for i in later} == {"slow", "cold"}
    assert all(i.cause for i in later)
    hit = list(itertools.islice(scenario.sick_servers(5), 30))
    assert len(set(hit)) > 4  # any server can be the slow one


def test_a_cold_server_warms_up():
    server = scenario.Server(random.Random(1))
    server.incident = scenario.Planned(10.0, 20.0, "cold", 9.0, "autoscaler")
    assert server.slow(9.9) == 1.0 and server.slow(10.0) == 9.0
    assert 1.0 < server.slow(15.0) < server.slow(12.0) < 9.0 and server.slow(20.0) == 1.0


def test_totals_survive_forgetting_old_minutes():
    world = build_world("load_balancing", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    asked = sum(len(p["tables"]["requests"]) for p in itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ask", 1e9) == asked


def test_a_bad_pick_names_the_problem():
    class Bad(RoundRobin):
        def pick(self, loads):
            return len(loads)  # one past the last server

    with pytest.raises(ValueError, match="pick"):
        next(scenario.stream(as_module(Bad)))


def test_both_pictures():
    from live.views import adapter_for, set_view, views_for

    world = build_world("load_balancing", "reference", 1)
    assert views_for(world) == ["relay", "cluster", "lanes"] and world.view == "relay"  # relay opens first
    set_view(world, "cluster")
    frame = adapter_for(world).frame("reference", 25.0)
    assert len(frame.nodes) == scenario.BALANCERS + scenario.SERVERS and frame.flights
    assert frame.nodes[scenario.BALANCERS + scenario.FIRST_SERVER] != frame.nodes[-1]  # the slow one stands out
    set_view(world, "lanes")
    lane = adapter_for(world).frame("reference", 25.0, 100)
    assert lane.users and lane.flights and lane.state[0]
    set_view(world, "relay")  # the balancers as a server of their own, between the door and the fleet
    relay = adapter_for(world).frame("reference", 25.0, 100)
    assert relay.users and relay.flights and relay.hops and relay.relay.label[0] and relay.state[0]


# ------------------------------------------------------------- your code


@your_code(1, "least_outstanding returns the index of the smallest load")
def test_stage1_least_outstanding():
    assert code.least_outstanding([3, 1, 2]) == 1
    assert code.least_outstanding([0.5, 2.0, 0.25, 7.0]) == 2
    assert code.least_outstanding([4, 4, 4]) in (0, 1, 2)
    loads = [5, 9, 1, 7, 3, 1.5, 8, 2]
    assert code.least_outstanding(list(loads)) == 2


@your_code(1, "the slow server gets less than its fair share")
def test_stage1_avoids_the_slow_server():
    world = build_world("load_balancing", variant(), 1)
    baseline, share, *_ = statuses(world, variant())[0]
    assert baseline and share


@your_code(2, "two_choices: the less loaded of two different servers, picked at random")
def test_stage2_two_choices():
    rng = random.Random(7)
    loads = [0, 1, 2, 3, 4, 5, 6, 7]  # server k is less loaded than every server after it
    picks = Counter(code.two_choices(list(loads), rng) for _ in range(5600))
    assert picks[7] == 0  # the busiest server always loses
    # Server k wins when it is drawn with a busier one: (7 - k) of the 28 pairs.
    for k in range(7):
        assert picks[k] == pytest.approx(5600 * (7 - k) / 28, rel=0.2), (k, picks)
    flat = Counter(code.two_choices([2] * 8, rng) for _ in range(4000))
    assert len(flat) == 8 and min(flat.values()) > 350  # equal loads: any server


@your_code(2, "every goal passes: the slow server avoided, no herds, p99 under 750 ms")
def test_stage2_all_goals_pass():
    world = build_world("load_balancing", variant(), 1)
    assert statuses(world, variant())[0] == [True] * 5
