import asyncio
import itertools

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.saga import scenario
from labs.saga.api import Declined, Order, SagaLog, StepFailed, Timeout, services

code = load("saga", variant(), scenario.NAMES)
ORDER = Order(7, 42, 1250, 2, "1 Main St")


class ROLLBACK:  # stage 1 as most people first write it: undo the steps whose refs came back
    class Orchestrator:
        def __init__(self, payments, stock, shipping, log):
            self.steps = [(payments.charge, payments.refund), (stock.reserve, stock.release),
                          (shipping.book, shipping.cancel)]

        async def place(self, saga_id, order):
            refs = []
            try:
                for do, _ in self.steps:
                    refs.append(await do(order))
                return True
            except StepFailed:
                await self.compensate(saga_id, refs)
                return False

        async def compensate(self, saga_id, refs):
            for (_, undo), ref in reversed(list(zip(self.steps, refs))):
                await undo(ref)

        async def recover(self):
            return


class RETRY_NO_KEYS:  # retries timeouts, but without keys: a retry after a lost answer charges again
    class Orchestrator(ROLLBACK.Orchestrator):
        async def place(self, saga_id, order):
            refs = []
            try:
                for do, _ in self.steps:
                    for n in range(6):
                        try:
                            refs.append(await do(order))
                            break
                        except Timeout:
                            if n == 5:
                                raise
                            await asyncio.sleep(0.1 * 2 ** n)
                return True
            except StepFailed:
                await self.compensate(saga_id, refs)
                return False


class NO_LOG:  # keys, retries and compensation by key, but nothing survives a crash
    class Orchestrator:
        def __init__(self, payments, stock, shipping, log):
            from labs.saga.reference import Orchestrator

            self.inner = Orchestrator(payments, stock, shipping, log)

        async def place(self, saga_id, order):
            return await self.inner.resume(saga_id, {"order": order, "status": "running"})

        async def recover(self):
            return


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def by_kind(world, v):
    run = world.runs[v]
    out: dict[str, list[list[bool]]] = {}
    for inc, res in zip(run.incidents, statuses(world, v)):
        out.setdefault(inc.kind, []).append(res)
    return out


# ------------------------------------------------------------- given behaviour


def test_starting_code_leaves_orders_half_done():
    world = build_world("saga", "main", 1)
    first = world.runs["main"].settled[0]
    # baseline, rolled back, half done, doubles, completed, p99
    assert [r.ok for r in first] == [True, False, False, True, False, True]
    assert world.stage_index("main") == 0  # No rollback


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_compensations_roll_back_failures_but_not_timeouts_or_crashes(seed):
    world = build_world("saga", ROLLBACK, 4, seed=seed)
    assert world.stage_index(ROLLBACK) == 1  # Compensations
    first = world.runs[ROLLBACK].settled[0]
    assert [r.ok for r in first][:3] == [True, True, False]  # rolled back, but some left half done
    for res in by_kind(world, ROLLBACK).get("stockout", []) + by_kind(world, ROLLBACK).get("shipping", []):
        assert res[1] and res[2]  # a definite no is rolled back completely


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_retrying_without_keys_lands_on_stage_1(seed):
    world = build_world("saga", RETRY_NO_KEYS, 4, seed=seed)
    assert world.stage_index(RETRY_NO_KEYS) == 1


def test_retrying_without_keys_charges_twice():
    world = build_world("saga", RETRY_NO_KEYS, 6, seed=1)
    run = world.runs[RETRY_NO_KEYS]
    payment_timeouts = [res for inc, res in zip(run.incidents, statuses(world, RETRY_NO_KEYS))
                        if inc.kind == "timeouts" and scenario.TIMEOUT_CAUSES[inc.cause] == 0]
    assert payment_timeouts and not any(res[3] for res in payment_timeouts)  # double charges


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_without_a_log_a_crash_leaves_orders_half_done(seed):
    world = build_world("saga", NO_LOG, 4, seed=seed)
    assert world.stage_index(NO_LOG) == 1
    first = world.runs[NO_LOG].settled[0]
    assert [r.ok for r in first][:4] == [True, True, False, True]  # the OOM kill cut sagas short


@pytest.mark.parametrize("seed", [1, 4, 9])
def test_reference_passes_every_goal_for_ten_minutes(seed):
    world = build_world("saga", "reference", 10, seed=seed)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 8 and len({i.kind for i in run.incidents}) >= 3
    assert all(all(r) for r in results), [(i.kind, r) for i, r in zip(run.incidents, results) if not all(r)]
    assert world.stage_index("reference") == 2  # Resumable sagas


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("saga", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["orders"] == sorted(run.keys["orders"])
    assert run.keys["orders"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    placed = sum(len(p["tables"]["orders"]) for p in pieces)
    assert run.total("orders", 1e9) == placed


# ------------------------------------------------------------- your code


def _orchestrator(timeouts=(0.0, 0.0, 0.0), refuse=(False, False, False), log=None, seed=0):
    pay, stock, ship = svcs = services(seed)
    for svc, share, no in zip(svcs, timeouts, refuse):
        svc.timeout_share = share
        svc.refuse = (lambda order: True) if no else (lambda order: False)
    log = log if log is not None else SagaLog()
    return code.Orchestrator(pay, stock, ship, log), svcs, log


def _held(svcs, order=ORDER.id):
    return [svc.held(order) for svc in svcs]


async def _place(orch, saga_id="order-7"):
    try:
        return await orch.place(saga_id, ORDER)
    except StepFailed:
        return "gave up"


@your_code(1, "a step that says no undoes the steps before it, last first")
def test_stage1_declined_step_is_compensated():
    async def main():
        orch, svcs, _ = _orchestrator(refuse=(False, False, True))  # the carrier says no
        undos = []
        for svc in svcs:
            svc.on_call = lambda start, order, s, undo, end, outcome: undo and s < 2 and undos.append(s)
        return await _place(orch), _held(svcs), undos

    ok, held, undos = run_virtual(main())
    assert ok is False and held == [0, 0, 0]
    assert undos == [1, 0]  # release the items, then refund the card


@your_code(1, "when the card is declined there is nothing to undo, and nothing breaks")
def test_stage1_first_step_declined():
    async def main():
        orch, svcs, _ = _orchestrator(refuse=(True, False, False))
        return await _place(orch), _held(svcs)

    assert run_virtual(main()) == (False, [0, 0, 0])


@your_code(2, "a step that times out is retried with the same key: one charge, one order")
def test_stage2_timeouts_are_retried_with_a_key():
    async def main(seed):
        orch, svcs, _ = _orchestrator(timeouts=(0.3, 0.0, 0.0), seed=seed)  # many charges time out
        return await _place(orch), _held(svcs), svcs[0].made(ORDER.id)

    for seed in range(5):
        assert run_virtual(main(seed)) == (True, [1, 1, 1], 1)


@your_code(2, "a step that timed out (and maybe happened) is undone too, by key")
def test_stage2_uncertain_step_is_undone_by_key():
    async def main():
        orch, svcs, _ = _orchestrator(timeouts=(0.0, 0.0, 1.0))  # every booking times out ...
        ship = svcs[2]
        ship.rng.random = lambda: 0.0  # ... after the courier was booked
        book_only = ship.undo

        async def undo(ref=None, key=None):  # cancelling answers in time
            ship.timeout_share = 0.0
            await book_only(ref, key)

        ship.undo = undo
        return await _place(orch), _held(svcs)

    ok, held = run_virtual(main())
    assert ok is False and held == [0, 0, 0]


@your_code(2, "a new orchestrator finishes the sagas a crash cut short (forward, or backward)")
def test_stage2_recover_after_a_crash():
    async def main():
        log = SagaLog()
        orch, svcs, _ = _orchestrator(log=log)
        task = asyncio.ensure_future(orch.place("order-7", ORDER))
        await asyncio.sleep(0.03)  # charging or reserving: then the orchestrator dies
        task.cancel()
        await asyncio.sleep(1.0)
        mid = _held(svcs)
        again = code.Orchestrator(*svcs, log)  # same services, same log, empty memory
        await again.recover()
        await asyncio.sleep(0.5)
        return mid, _held(svcs), svcs[0].made(ORDER.id), len(log)

    mid, held, charges, left = run_virtual(main())
    assert mid != [1, 1, 1] and mid != [0, 0, 0]  # half done when it died
    assert held in ([1, 1, 1], [0, 0, 0]) and charges == 1 and left == 0


@your_code(2, "no order left half done on the first incident: every goal OK")
def test_stage2_first_incident_every_goal():
    world = build_world("saga", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first] == [True] * 6


def test_two_pictures_cluster_first():
    from live.canvas import EXTRA2, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v, t: float):
        world = build_world("saga", v, 1)
        assert views_for(world) == ["cluster", "lanes"] and world.view == "cluster"  # cluster opens first
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == 4 and any(src == -1 for src, _, _, _ in frame.flights)
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        return world, frame, lanes

    world, down, lanes = picture("main", 27.0)  # the orchestrator is dead (OOM kill at 0:26)
    assert down.nodes[0] == RED and lanes.closed
    _, given, _ = picture("main", 23.0)
    _, solved, _ = picture("reference", 23.0)
    # Without compensations, services hold money and items for orders that will never complete (red);
    # with them, compensations fly in orange and nothing is held.
    assert RED in given.nodes[1:]
    assert RED not in solved.nodes and any(c == EXTRA2 for _, _, _, c in solved.flights)
