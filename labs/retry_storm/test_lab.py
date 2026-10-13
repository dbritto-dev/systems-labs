import asyncio
import itertools
import random
from core.contract import load
from core.services import FaultyService, ServiceError, current_request
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.retry_storm import scenario

code = load("retry_storm", variant(), scenario.NAMES)


def retrying_client(wait):
    """A Client that retries 3 times, sleeping wait(attempt, rng) between tries, with no budget."""

    class Client:
        def __init__(self, service, rng=None):
            self.service, self.rng = service, rng

        async def call(self, payload=None):
            for attempt in range(4):
                try:
                    return await self.service.call(payload)
                except ServiceError:
                    if attempt == 3:
                        raise
                    await asyncio.sleep(wait(attempt + 1, self.rng))

    return Client


class NAIVE:  # stage 1 as most people first write it: 3 quick retries, 50 ms apart
    Client = retrying_client(lambda attempt, rng: 0.05)
    backoff_delay = RetryBudget = None


class BACKOFF_ONLY:  # stage 2: exponential backoff, the same for every user
    Client = retrying_client(lambda attempt, rng: min(5.0, 0.1 * 2 ** attempt))
    backoff_delay = RetryBudget = None


class JITTER_ONLY:  # stage 3: backoff with full jitter, but no budget yet
    Client = retrying_client(lambda attempt, rng: rng.uniform(0, min(5.0, 0.1 * 2 ** attempt)))
    backoff_delay = RetryBudget = None


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_starting_code_runs_and_fails_users_during_the_outage():
    world = build_world("retry_storm", "main", 1)
    assert world.stage("main") is not None
    piece = scenario.run("main", chunk=0)
    failed = [r for r in piece["tables"]["requests"] if not r[3]]
    assert failed and all(19.9 <= r[1] < 30.1 for r in failed)


def test_naive_retry_is_in_lockstep_and_fails_the_load_goal_on_every_outage():
    world = build_world("retry_storm", NAIVE, 8)
    results = statuses(world, NAIVE)
    kinds = {i.kind for i in world.runs[NAIVE].incidents}
    assert len(results) >= 6 and kinds == {"outage", "errors"}  # full and partial outages
    assert all(r == [True, True, False, False, False, True] for r in results)  # no backoff, no jitter
    assert world.stage(NAIVE).label == "Retry"


def test_backoff_without_jitter_comes_back_in_waves():
    world = build_world("retry_storm", BACKOFF_ONLY, 4)
    results = statuses(world, BACKOFF_ONLY)
    assert len(results) >= 3
    assert all(r == [True, True, True, False, False, True] for r in results)
    assert world.stage(BACKOFF_ONLY).label == "Retry + backoff"


def test_jitter_without_a_budget_still_fails_the_load_goal():
    world = build_world("retry_storm", JITTER_ONLY, 4)
    results = statuses(world, JITTER_ONLY)
    assert len(results) >= 3
    assert all(r == [True, True, True, True, False, True] for r in results)
    assert world.stage(JITTER_ONLY).label == "Retry + backoff + jitter"


def test_reference_passes_every_goal_on_the_first_eight_outages():
    world = build_world("retry_storm", "reference", 9)
    results = statuses(world, "reference")
    assert len(results) >= 8
    assert all(all(r) for r in results[:8])
    assert world.stage("reference").label == "Retry + backoff + jitter + budget"


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("retry_storm", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["calls"] == sorted(run.keys["calls"])
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    asked = sum(len(p["tables"]["requests"]) for p in pieces)
    assert run.total("ask", 1e9) == asked


# ------------------------------------------------------------- your code


def _calls(client_factory, down=True, exc=None):
    async def main():
        svc = FaultyService(rng=random.Random(1))
        svc.set_down(down)
        if exc is not None:
            async def boom(payload=None):
                svc.events.append(None)
                raise exc
            svc.call = boom
        client = client_factory(svc)
        current_request.set(1)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            await client.call("x")
            outcome = "ok"
        except ServiceError:
            outcome = "ServiceError"
        except Exception as e:  # noqa: BLE001
            outcome = type(e).__name__
        return outcome, len(svc.events), loop.time() - t0

    return run_virtual(main())


@your_code(1, "Client retries ServiceError up to 3 times, then re-raises")
def test_stage1_client_retries_then_gives_up():
    outcome, events, _ = _calls(lambda s: code.Client(s, rng=random.Random(1)))
    assert outcome == "ServiceError"
    assert events == 8  # 4 calls, each a start and an error


@your_code(1, "Client never catches other exceptions")
def test_stage1_other_exceptions_are_not_retried():
    outcome, events, _ = _calls(lambda s: code.Client(s, rng=random.Random(1)), exc=KeyError("bug"))
    assert outcome == "KeyError" and events == 1


@your_code(2, "backoff_delay grows exponentially, with a cap")
def test_stage2_backoff_delay_grows():
    rng = random.Random(3)
    means = []
    for attempt in range(1, 6):
        top = min(5.0, 0.1 * 2 ** attempt)
        values = [code.backoff_delay(attempt, rng=rng) for _ in range(400)]
        assert all(0 <= v <= top + 1e-9 for v in values)
        means.append(sum(values) / len(values))
    assert all(b > 1.6 * a for a, b in zip(means, means[1:]))  # about twice as long each time
    assert code.backoff_delay(10_000, rng=rng) <= 5.0  # capped, and no overflow


@your_code(2, "Client sleeps backoff_delay between retries: the waits grow")
def test_stage2_client_backs_off():
    world = build_world("retry_storm", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first][:3] == [True, True, True]


@your_code(3, "backoff_delay uses full jitter: anywhere from 0 to the backoff")
def test_stage3_backoff_delay_jitter():
    rng = random.Random(3)
    for attempt in range(1, 8):
        top = min(5.0, 0.1 * 2 ** attempt)
        values = [code.backoff_delay(attempt, rng=rng) for _ in range(200)]
        assert all(0 <= v <= top for v in values)
        assert max(values) > top * 0.8 and min(values) < top * 0.2  # spread over the whole range


@your_code(3, "retries are jittered, so users do not come back in waves")
def test_stage3_retries_are_jittered():
    world = build_world("retry_storm", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first][:4] == [True, True, True, True]


@your_code(4, "RetryBudget deposits a fraction and spends whole tokens")
def test_stage4_retry_budget():
    b = code.RetryBudget(ratio=0.1, max_tokens=10)
    assert sum(b.try_withdraw() for _ in range(15)) == 10  # starts full
    for _ in range(25):
        b.deposit()
    assert sum(b.try_withdraw() for _ in range(5)) == 2  # 25 deposits = 2.5 tokens
    for _ in range(1000):
        b.deposit()
    assert sum(b.try_withdraw() for _ in range(50)) == 10  # never above max_tokens


@your_code(4, "Client keeps the load under 1.5x during an outage")
def test_stage4_load_goal_passes():
    world = build_world("retry_storm", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first] == [True] * 6
