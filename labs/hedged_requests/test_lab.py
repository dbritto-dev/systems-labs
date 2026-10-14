import asyncio
import itertools
import random

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.hedged_requests import scenario
from labs.hedged_requests.reference import HEDGE_AFTER, HedgeBudget

code = load("hedged_requests", variant(), scenario.NAMES)


class OneCallClient:
    """Stage 0, as given: one replica, wait as long as it takes."""

    def __init__(self, replicas, rng=None):
        self.replicas, self.rng = replicas, rng or random.Random(0)

    async def read(self, key):
        return await self.rng.choice(self.replicas).get(key)


class HedgeClient(OneCallClient):
    """Stage 1: a copy after HEDGE_AFTER, the first answer wins; no budget, nothing cancelled."""

    cancel = False

    def allow(self) -> bool:
        return True

    async def read(self, key):
        first, second = self.rng.sample(self.replicas, 2)
        calls = [asyncio.ensure_future(first.get(key))]
        try:
            done, _ = await asyncio.wait(calls, timeout=HEDGE_AFTER)
            if not done and self.allow():
                calls.append(asyncio.ensure_future(second.get(key)))
            done, _ = await asyncio.wait(calls, return_when=asyncio.FIRST_COMPLETED)
            return done.pop().result()
        finally:
            if self.cancel:
                for c in calls:
                    c.cancel()


class BudgetOnlyClient(HedgeClient):
    """Half of stage 2: a budget, but the loser keeps running."""

    def __init__(self, replicas, rng=None):
        super().__init__(replicas, rng)
        self.budget = HedgeBudget()

    def allow(self) -> bool:
        return self.budget.try_withdraw()

    async def read(self, key):
        self.budget.deposit()
        return await super().read(key)


class CancelOnlyClient(HedgeClient):
    """The other half: losers cancelled, but a copy for every slow read."""

    cancel = True


def _module(client):  # stands in for a main.py module
    return type(client.__name__, (), {"Client": client, "HedgeBudget": HedgeBudget})


ONE_CALL, HEDGE, BUDGET_ONLY, CANCEL_ONLY = map(_module, (OneCallClient, HedgeClient, BudgetOnlyClient,
                                                          CancelOnlyClient))


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_one_call_lets_the_rare_slow_replies_set_the_p99():
    for seed in (1, 2, 3):
        world = build_world("hedged_requests", ONE_CALL, 2, seed=seed)
        results = statuses(world, ONE_CALL)
        assert results and all(r == [False, True, True, True, False] for r in results)
        assert world.stage_index(ONE_CALL) == 0  # One call


def test_hedging_without_a_budget_costs_a_copy_per_slow_read():
    for seed in (1, 2, 3):
        world = build_world("hedged_requests", HEDGE, 1, seed=seed)
        first = world.runs[HEDGE].settled[0]
        assert [r.ok for r in first] == [True, False, False, True, True]
        assert world.stage_index(HEDGE) == 1  # Hedge


def test_a_budget_alone_or_cancelling_alone_is_still_stage_one():
    for v in (BUDGET_ONLY, CANCEL_ONLY):
        for seed in (1, 2):
            world = build_world("hedged_requests", v, 1, seed=seed)
            first = world.runs[v].settled[0]
            # The budget caps the extra load but wastes work; cancelling alone does the opposite.
            assert [r.ok for r in first][1:3] == ([True, False] if v is BUDGET_ONLY else [False, True])
            assert world.stage_index(v) == 1


def test_reference_passes_every_goal():
    world = build_world("hedged_requests", "reference", 6)
    results = statuses(world, "reference")
    kinds = {i.kind == "all" for i in world.runs["reference"].incidents}
    assert len(results) >= 4 and kinds == {True, False}  # one replica slow, and all of them
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Hedge + budget + cancel


def test_pieces_join_and_the_first_incident_is_fixed():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "r1") for i in first)
    pieces = list(itertools.islice(scenario.stream("reference"), 2))
    starts = [r[1] for p in pieces for r in p["tables"]["requests"]]
    assert starts == sorted(starts) and starts[-1] < 120
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)


# ------------------------------------------------------------- your code


class FakeReplica:
    """Answers after `latency` seconds; records calls and cancellations."""

    def __init__(self, latency: float) -> None:
        self.latency = latency
        self.calls = self.cancelled = 0

    async def get(self, key):
        self.calls += 1
        try:
            await asyncio.sleep(self.latency)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return f"value-{key}"


def _read(client, key="k"):
    async def one():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        value = await client.read(key)
        return value, loop.time() - t0
    return one()


class _Fixed(random.Random):
    """Picks replicas in list order, so a test knows which one is asked first."""

    def choice(self, seq):
        return seq[0]

    def sample(self, population, k, **kw):
        return list(population)[:k]


@your_code(1, "Client sends a copy to another replica after HEDGE_AFTER (only then) and returns the first answer")
def test_stage1_hedges_a_slow_read():
    async def main():
        slow, fast, spare = FakeReplica(0.5), FakeReplica(0.01), FakeReplica(0.01)
        client = code.Client([slow, fast, spare], rng=_Fixed())
        value, took = await _read(client)
        return value, took, slow.calls, fast.calls + spare.calls

    value, took, slow_calls, other_calls = run_virtual(main())
    assert value == "value-k"
    assert slow_calls == 1 and other_calls == 1  # one copy, to another replica
    assert took <= HEDGE_AFTER + 0.01 + 1e-6

    async def fast():  # and no copy when the first replica answers in time
        replicas = [FakeReplica(0.005) for _ in range(3)]
        client = code.Client(replicas, rng=random.Random(1))
        for _ in range(20):
            assert (await _read(client))[0] == "value-k"
        return sum(r.calls for r in replicas)

    assert run_virtual(fast()) == 20


@your_code(2, "HedgeBudget adds `ratio` per read up to `max_tokens`, and spends one per copy")
def test_stage2_budget():
    b = code.HedgeBudget(ratio=0.5, max_tokens=2)
    assert [b.try_withdraw() for _ in range(3)] == [True, True, False]
    b.deposit()
    assert not b.try_withdraw()
    b.deposit()
    assert b.try_withdraw() and not b.try_withdraw()
    for _ in range(10):
        b.deposit()
    assert b.tokens == 2


@your_code(2, "Client cancels the call that lost the race")
def test_stage2_cancels_the_loser():
    async def main():
        slow, fast, spare = FakeReplica(0.5), FakeReplica(0.01), FakeReplica(0.01)
        client = code.Client([slow, fast, spare], rng=_Fixed())
        value, _ = await _read(client)
        await asyncio.sleep(0)  # let the cancellation land
        return value, slow.cancelled

    assert run_virtual(main()) == ("value-k", 1)


@your_code(2, "Client stops sending copies once the budget is spent")
def test_stage2_budget_caps_the_copies():
    async def main():
        replicas = [FakeReplica(0.05) for _ in range(3)]  # every reply is slower than HEDGE_AFTER
        client = code.Client(replicas, rng=random.Random(1))
        for _ in range(200):
            await _read(client)
        return sum(r.calls for r in replicas) - 200

    copies = run_virtual(main())
    assert 1 <= copies <= 10 + 0.05 * 200 + 1


@your_code(2, "Client keeps every goal on the first slowdown")
def test_stage2_first_slowdown():
    world = build_world("hedged_requests", variant(), 1)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 5


def test_both_pictures():
    from live.views import adapter_for, set_view, views_for

    world = build_world("hedged_requests", "reference", 1)
    assert sorted(views_for(world)) == ["cluster", "lanes"] and world.view == "cluster"
    frame = adapter_for(world).frame("reference", 25.0)
    assert len(frame.nodes) == 4 and frame.flights and frame.state[0]
    set_view(world, "lanes")
    lanes = adapter_for(world).frame("reference", 25.0, 60)
    assert lanes.users and lanes.state[0]
