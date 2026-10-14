import asyncio
import itertools

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import now, run_virtual
from labs.graceful_shutdown import scenario

code = load("graceful_shutdown", variant(), scenario.NAMES)
MINUTES = 2  # the first incident (a deploy at 0:20) is judged at 1:11, once its last instance is gone


async def _drain(server, deadline):
    server.stop_accepting()
    server.close_idle()
    await server.drained(deadline)
    server.exit()


async def _shutdown(server, wait):
    server.fail_readiness()
    await asyncio.sleep(wait)
    await _drain(server, server.grace - wait - 5)


def as_module(name, on_sigterm):
    return type(name, (), {"on_sigterm": staticmethod(on_sigterm), "drain": staticmethod(_drain),
                           "shutdown": staticmethod(_shutdown)})


async def exit_at_once(server):  # stage 0
    server.exit()


async def drain(server):  # stage 1
    await _drain(server, server.grace - 5)


async def drain_and_fail_readiness(server):  # stage 1: readiness off, but the listener closes at once too
    server.fail_readiness()
    await _drain(server, server.grace - 5)


async def readiness_first(server):  # stage 2
    await _shutdown(server, 8.0)


async def readiness_first_no_margin(server):  # interval x threshold only: the balancer needs 1 s more
    await _shutdown(server, 6.0)


async def drain_keeping_connections(server):  # no close_idle(): streams and kept-alive clients never leave
    server.stop_accepting()
    await server.drained(server.grace - 5)
    server.exit()


async def drain_without_deadline(server):  # waits for ever: the hard kill
    server.stop_accepting()
    await server.drained()
    server.exit()


async def sleep_past_the_kill(server):
    server.fail_readiness()
    await asyncio.sleep(35)
    await _drain(server, 5)


EXIT, DRAIN, DRAIN_READY, READY_FIRST, NO_MARGIN, KEEP_CONNS, NO_DEADLINE, TOO_LONG = (
    as_module(f.__name__.upper(), f) for f in (
        exit_at_once, drain, drain_and_fail_readiness, readiness_first, readiness_first_no_margin,
        drain_keeping_connections, drain_without_deadline, sleep_past_the_kill))


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def first(world, v):
    run = world.runs[v]
    return {g.key: r for g, r in zip(world.goals, run.settled[0])}


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("module, stage", [
    (EXIT, 0),  # Exit at once
    (KEEP_CONNS, 0),  # drains, but streams never end: cut at the deadline
    (NO_DEADLINE, 0),  # drains for ever: killed
    (TOO_LONG, 0),  # sleeps past the hard kill
    (DRAIN, 1),  # Drain
    (DRAIN_READY, 1),  # readiness off, but it stops accepting at once
    (NO_MARGIN, 1),  # readiness off first, but leaves a second too early
    (READY_FIRST, 2),  # Readiness off first
])
def test_each_stage_is_judged_from_what_the_run_did(module, stage, seed):
    world = build_world("graceful_shutdown", module, MINUTES, seed=seed)
    baseline, errors, cut, capacity, exited = statuses(world, module)[0]
    assert world.stage_index(module) == stage
    assert baseline
    assert (cut and exited) == (stage >= 1)
    assert (errors and capacity) == (stage >= 2) or stage == 0


def test_exit_at_once_cuts_work_in_flight_and_the_balancer_still_sends():
    world = build_world("graceful_shutdown", EXIT, MINUTES)
    goals = first(world, EXIT)
    run = world.runs[EXIT]
    stopped = run.rows("instances", 19.9, 50.0)
    assert len(stopped) == scenario.INSTANCES and all(r[1] - r[0] < 0.01 for r in stopped)  # no drain at all
    assert sum(r[4] for r in stopped) > 100  # requests and streams cut mid-flight
    refused = [r for r in run.rows("requests", 20.0, 50.0) if r[4] == scenario.REFUSED]
    assert len(refused) > 300  # sent to an instance that is gone
    assert goals["capacity"].value in ("3/6", "4/6")  # the next one stops before the new one is in rotation


def test_drain_cuts_nothing_but_the_balancer_still_sends():
    world = build_world("graceful_shutdown", DRAIN, MINUTES)
    run = world.runs[DRAIN]
    stopped = run.rows("instances", 19.9, 50.0)
    assert sum(r[4] for r in stopped) == 0 and not any(r[3] for r in stopped)
    refused = [r for r in run.rows("requests", 20.0, 50.0) if r[4] == scenario.REFUSED]
    assert len(refused) > 300  # the listener is closed, the balancer does not know yet
    assert all(r[8] for r in refused)  # every one sent to an instance that got SIGTERM


def test_readiness_first_serves_until_the_balancer_lets_go():
    world = build_world("graceful_shutdown", READY_FIRST, MINUTES)
    run = world.runs[READY_FIRST]
    reqs = run.rows("requests", 20.0, 50.0)
    assert not any(r[4] == scenario.REFUSED for r in reqs)
    assert sum(r[8] for r in reqs) > 1000  # old instances keep serving while they wait
    assert first(world, READY_FIRST)["capacity"].value == "5/6"


def test_the_balancer_takes_a_failing_instance_out_within_its_checks_and_delay():
    """Readiness off at 20.0: every node stops sending new connections within 3 checks x 2 s + 1 s."""
    world = build_world("graceful_shutdown", READY_FIRST, MINUTES)
    run = world.runs[READY_FIRST]
    fresh = [r for r in run.rows("requests", 20.0, 32.0) if r[5] == 0 and r[8] and not r[7]]
    last = max(r[1] for r in fresh)
    worst = scenario.INTERVAL * scenario.UNHEALTHY + scenario.DEREGISTRATION
    assert 20.0 + worst - 2.5 < last <= 20.0 + worst


def test_reference_passes_every_goal():
    for seed in (1, 2, 3):
        world = build_world("graceful_shutdown", "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 4
        assert all(all(r) for r in results), (seed, results)
        assert world.stage_index("reference") == 2  # Readiness off first


def test_one_run_never_restarts_and_incidents_come_at_random():
    pieces = list(itertools.islice(scenario.stream("reference"), 4))
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 50.0, "deploy") for i in firsts)
    later = list(itertools.islice(scenario.incidents(5), 30))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET and {i.kind for i in later} == {"deploy", "drain", "scale_in"}
    assert all(i.cause for i in later)
    assert len(set(itertools.islice(scenario.hit_slots(5), 30))) > 3  # any instance can be the one


def test_totals_survive_forgetting_old_minutes():
    world = build_world("graceful_shutdown", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    asked = sum(len(p["tables"]["requests"]) for p in itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ask", 1e9) == asked


def test_mistakes_name_the_problem():
    async def bad_timeout(server):
        await server.drained("10")

    with pytest.raises(TypeError, match="drained"):
        list(itertools.islice(scenario.stream(as_module("BAD", bad_timeout)), 1))

    async def crash(server):
        raise RuntimeError("boom in on_sigterm")

    with pytest.raises(RuntimeError, match="boom"):
        list(itertools.islice(scenario.stream(as_module("CRASH", crash)), 1))


def test_both_pictures():
    from live.views import adapter_for, set_view, views_for

    world = build_world("graceful_shutdown", EXIT, 1)
    assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
    lane = adapter_for(world).frame(EXIT, 22.0, 100)
    assert lane.users and lane.flights and lane.closed  # the balancer still sends to the dead instance
    set_view(world, "cluster")
    frame = adapter_for(world).frame(EXIT, 22.0)
    assert len(frame.nodes) == scenario.LB_NODES + scenario.INSTANCES and frame.flights and frame.drops


# ------------------------------------------------------------- your code


class FakeServer:
    """Records what your code does, and when."""

    health_interval, unhealthy_threshold, deregistration_delay, grace = 2.0, 3, 1.0, 30.0

    def __init__(self, busy_for: float = 2.0) -> None:
        self.calls: list[tuple[str, float]] = []
        self.busy_until = busy_for  # in-flight work ends then (if idle connections were closed)

    def _log(self, what):
        self.calls.append((what, round(now(), 3)))

    def fail_readiness(self):
        self._log("fail_readiness")

    def stop_accepting(self):
        self._log("stop_accepting")

    def close_idle(self):
        self._log("close_idle")
        self.busy_until = now() + 2.0

    @property
    def in_flight(self):
        return 3 if now() < self.busy_until else 0

    async def drained(self, timeout=None):
        self._log(f"drained({timeout})")
        end = now() + (timeout if timeout is not None else 1e9)
        while self.in_flight and now() < end:
            await asyncio.sleep(0.05)
        return not self.in_flight

    def exit(self):
        self._log("exit")


def names(server):
    return [c.split("(")[0] for c, _ in server.calls]


@your_code(1, "drain: stop accepting, close idle connections, wait with a deadline, then exit")
def test_stage1_drain():
    server = FakeServer(busy_for=1e9)  # busy until idle connections are closed
    run_virtual(code.drain(server, 25.0))
    assert names(server) == ["stop_accepting", "close_idle", "drained", "exit"]
    assert server.calls[-1][1] == pytest.approx(2.0, abs=0.1)  # it waited for the work in flight
    stuck = FakeServer(busy_for=1e9)
    stuck.close_idle = lambda: stuck._log("close_idle")  # work that never ends
    run_virtual(code.drain(stuck, 10.0))
    assert stuck.calls[-1] == ("exit", pytest.approx(10.0, abs=0.1))  # the deadline holds


@your_code(1, "nothing is cut mid-flight and no instance is killed")
def test_stage1_cuts_nothing():
    world = build_world("graceful_shutdown", variant(), MINUTES)
    _, _, cut, _, exited = statuses(world, variant())[0]
    assert cut and exited


@your_code(2, "shutdown: readiness off, wait for the balancer, then drain before the hard kill")
def test_stage2_shutdown():
    server = FakeServer(busy_for=1e9)
    run_virtual(code.shutdown(server))
    assert names(server) == ["fail_readiness", "stop_accepting", "close_idle", "drained", "exit"]
    calls = dict(server.calls)
    assert calls["fail_readiness"] == 0.0
    worst = server.health_interval * server.unhealthy_threshold + server.deregistration_delay
    assert worst < calls["stop_accepting"] <= 12.0  # after every node took it out, not much later
    assert calls["exit"] < server.grace - 2  # well before the hard kill
    drained = next(c for c, _ in server.calls if c.startswith("drained"))
    deadline = float(drained[len("drained("):-1])
    assert calls["stop_accepting"] + deadline < server.grace  # the deadline ends before the hard kill


@your_code(2, "every goal passes: no errors, nothing cut, 5 of 6 serving, exit before the kill")
def test_stage2_all_goals_pass():
    world = build_world("graceful_shutdown", variant(), MINUTES)
    assert statuses(world, variant())[0] == [True] * 5
