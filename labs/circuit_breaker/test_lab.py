import asyncio
import itertools
import random

from core.contract import load
from core.services import FaultyService, ServiceError
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.circuit_breaker import scenario
from labs.circuit_breaker.reference import BULKHEAD_LIMIT, TIMEOUT, Bulkhead, CircuitBreaker

code = load("circuit_breaker", variant(), scenario.NAMES)


class TimeoutClient:
    """Stage 1: a timeout on every call, nothing else."""

    def __init__(self, deps, rng=None):
        self.deps = deps

    async def call(self, dep, payload=None):
        try:
            async with asyncio.timeout(TIMEOUT):
                return await self.deps[dep].call(payload)
        except TimeoutError:
            raise ServiceError("timed out") from None


class BulkheadClient(TimeoutClient):
    """Stage 2: timeouts and a bulkhead per dependency, no breaker."""

    def __init__(self, deps, rng=None):
        super().__init__(deps)
        self.bulkheads = {d: Bulkhead(BULKHEAD_LIMIT) for d in deps}

    async def call(self, dep, payload=None):
        bulkhead = self.bulkheads[dep]
        if not bulkhead.try_enter():
            raise ServiceError("bulkhead full")
        try:
            return await super().call(dep, payload)
        finally:
            bulkhead.leave()


class TIMEOUTS:  # stands in for a main.py module
    Client = TimeoutClient
    Bulkhead, CircuitBreaker = Bulkhead, CircuitBreaker


class BULKHEADS:
    Client = BulkheadClient
    Bulkhead, CircuitBreaker = Bulkhead, CircuitBreaker


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_starting_code_lets_one_slow_dependency_take_every_worker():
    world = build_world("circuit_breaker", "main", 2)
    results = statuses(world, "main")
    assert results and all(r[:4] == [True, False, False, False] for r in results)
    assert world.stage_index("main") == 0  # No protection


def test_timeouts_alone_still_fill_the_pool():
    world = build_world("circuit_breaker", TIMEOUTS, 6)
    results = statuses(world, TIMEOUTS)
    assert len(results) >= 4
    assert all(r[:4] == [True, True, False, False] for r in results)
    assert world.stage_index(TIMEOUTS) == 1  # Timeouts


def test_a_bulkhead_saves_the_healthy_dependency_but_users_still_wait():
    world = build_world("circuit_breaker", BULKHEADS, 6)
    results = statuses(world, BULKHEADS)
    assert len(results) >= 4
    assert all(r == [True, True, True, False, True] for r in results)
    assert world.stage_index(BULKHEADS) == 2  # + bulkhead


def test_reference_passes_every_goal_on_the_first_incidents():
    world = build_world("circuit_breaker", "reference", 8)
    results = statuses(world, "reference")
    kinds = {i.kind for i in world.runs["reference"].incidents}
    assert len(results) >= 5 and kinds == {"payments", "recs"}
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 3  # + breaker


def test_pieces_join_and_the_first_incident_is_fixed():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "recs") for i in first)
    pieces = list(itertools.islice(scenario.stream("reference"), 3))
    starts = [r[1] for p in pieces for r in p["tables"]["requests"]]
    assert starts == sorted(starts) and starts[-1] < 180
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)


# ------------------------------------------------------------- your code


def _deps(latency: float):
    class Dep:
        def __init__(self):
            self.svc = FaultyService(latency=latency, rng=random.Random(1))
            self.calls = 0

        async def call(self, payload=None):
            self.calls += 1
            return await self.svc.call(payload)

    return {"payments": Dep(), "recs": Dep()}


def _outcome(client, dep="recs"):
    async def one():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            await client.call(dep)
            return "ok", loop.time() - t0
        except ServiceError:
            return "ServiceError", loop.time() - t0
    return one()


@your_code(1, "Client gives up on a slow call after TIMEOUT, with a ServiceError")
def test_stage1_timeout():
    async def main():
        client = code.Client(_deps(latency=8.0), rng=random.Random(1))
        return await _outcome(client)

    outcome, took = run_virtual(main())
    assert outcome == "ServiceError" and took <= 1.0 + 1e-6


@your_code(2, "Bulkhead lets `limit` in at once and refuses the rest")
def test_stage2_bulkhead():
    b = code.Bulkhead(3)
    assert [b.try_enter() for _ in range(5)] == [True, True, True, False, False]
    b.leave()
    assert b.try_enter() and not b.try_enter()


@your_code(2, "Client refuses calls beyond the bulkhead at once")
def test_stage2_client_uses_a_bulkhead():
    async def main():
        deps = _deps(latency=8.0)
        client = code.Client(deps, rng=random.Random(1))
        results = await asyncio.gather(*(_outcome(client) for _ in range(30)))
        return deps["recs"].calls, results

    calls, results = run_virtual(main())
    assert calls <= 10
    assert sum(took < 0.01 for _, took in results) >= 20  # the rest were refused at once


@your_code(3, "CircuitBreaker opens after failures, probes after the cool-down, closes on success")
def test_stage3_breaker_states():
    async def main():
        br = code.CircuitBreaker(failures=3, cooldown=5.0)
        seen = []
        for _ in range(3):
            assert br.allow()
            br.record_failure()
        seen.append(br.allow())  # open: refused
        await asyncio.sleep(5.0)
        seen.append(br.allow())  # half-open: one probe
        seen.append(br.allow())  # the probe is still out: refused
        br.record_failure()  # the probe failed: open again
        seen.append(br.allow())
        await asyncio.sleep(5.0)
        seen.append(br.allow())
        br.record_success()  # closed
        seen += [br.allow(), br.allow()]
        return seen

    assert run_virtual(main()) == [False, True, False, False, True, True, True]


@your_code(3, "Client fails fast while the dependency is down")
def test_stage3_client_fails_fast():
    world = build_world("circuit_breaker", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first] == [True] * 5
