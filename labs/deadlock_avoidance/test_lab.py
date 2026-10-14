import asyncio
import itertools
import random

import pytest

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import run_virtual
from labs.deadlock_avoidance import reference, scenario
from labs.deadlock_avoidance.api import Audit, Ledger, LockManager, LockTimeout, Request, current_request

code = load("deadlock_avoidance", variant(), scenario.NAMES)
SEEDS = (1, 2, 3)


class _Variant(reference.Payments):
    """A Payments with the knobs the stages turn: the lock order, the timeout, the tries, the jitter,
    and whether the audit write happens while holding the locks."""

    ORDER = staticmethod(list)
    TIMEOUT = None
    TRIES = 1
    JITTER = True
    AUDIT_INSIDE = True
    BOTH = True  # lock both accounts (not only the payer's)

    async def lock_all(self, accounts):
        for attempt in range(1, self.TRIES + 1):
            try:
                for account in accounts:
                    await self.locks.acquire(account, timeout=self.TIMEOUT)
                return
            except LockTimeout:
                self.locks.release_all()
                if attempt == self.TRIES:
                    raise
                wait = reference.backoff(attempt, self.rng) if self.JITTER else min(0.2, 0.01 * 2 ** attempt)
                await asyncio.sleep(wait)

    async def _apply(self, accounts, entries):
        await self.lock_all(self.ORDER(accounts))
        try:
            await self.ledger.apply(entries)
            if self.AUDIT_INSIDE:
                await self.audit.record(entries)
        finally:
            self.locks.release_all()
        if not self.AUDIT_INSIDE:
            await self.audit.record(entries)

    async def transfer(self, src, dst, amount):
        await self._apply([src, dst] if self.BOTH else [src], [(src, -amount), (dst, amount)])

    async def settle(self, entries):
        await self._apply([a for a, _ in entries], entries)


def _variant(name: str, **knobs):
    payments = type("Payments", (_Variant,), knobs)
    return type(name, (), {"Payments": payments, "LOCK_TIMEOUT": knobs.get("TIMEOUT")})


REQUEST_ORDER = _variant("REQUEST_ORDER")  # the given code: src first, then dst, waiting forever
SORTED = staticmethod(lambda accounts: sorted(set(accounts)))
TIMEOUTS = _variant("TIMEOUTS", TIMEOUT=0.05, TRIES=8)  # stage 1: request order, timeouts, retry with jitter
NO_JITTER = _variant("NO_JITTER", TIMEOUT=0.05, TRIES=8, JITTER=False)  # stage 1, retries in step
GIVE_UP = _variant("GIVE_UP", TIMEOUT=0.05)  # a timeout and no retry: the client gets an error
ORDER_ONLY = _variant("ORDER_ONLY", ORDER=SORTED)  # one lock order, but the audit write holds the locks
ORDER_SLOW_TIMEOUT = _variant("ORDER_SLOW_TIMEOUT", ORDER=SORTED, TIMEOUT=0.05, TRIES=8)  # ...and short timeouts
PAYER_ONLY = _variant("PAYER_ONLY", BOTH=False, ORDER=SORTED, AUDIT_INSIDE=False)  # never deadlocks: loses money


def first(v, seed=1):
    world = build_world("deadlock_avoidance", v, 1, seed=seed)
    return world, [r.ok for r in world.runs[v].settled[0]]


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_starting_code_deadlocks_and_freezes_in_the_payout_run():
    world, ok = first("main")
    assert not ok[0] and not ok[1] and not ok[2]  # a deadlock nobody breaks, then nothing completes
    assert ok[4]  # but no money is lost: the locks still protect the balances
    assert world.stage_index("main") == 0  # Request order


@pytest.mark.parametrize("seed", SEEDS)
def test_timeouts_never_freeze_but_retry_a_lot(seed):
    world, ok = first(TIMEOUTS, seed)
    assert ok[0] and ok[4] and not (ok[2] and ok[3])
    assert world.stage_index(TIMEOUTS) == 1  # Timeouts and retry


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_retrying_in_step_is_no_better(seed):
    world, ok = first(NO_JITTER, seed)
    assert ok[0] and not ok[3]
    assert world.stage_index(NO_JITTER) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_giving_up_on_a_timeout_fails_transfers(seed):
    world, ok = first(GIVE_UP, seed)
    assert ok[0] and not ok[1]
    assert world.stage_index(GIVE_UP) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_one_lock_order_with_a_slow_critical_section_is_slow(seed):
    world, ok = first(ORDER_ONLY, seed)
    assert ok[0] and not ok[2]  # no deadlock, but transfers queue behind audit writes
    assert world.stage_index(ORDER_ONLY) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_one_lock_order_with_short_timeouts_still_retries(seed):
    world, ok = first(ORDER_SLOW_TIMEOUT, seed)
    assert ok[0] and not (ok[2] and ok[3])
    assert world.stage_index(ORDER_SLOW_TIMEOUT) == 1


def test_locking_only_the_payer_loses_money():
    world, ok = first(PAYER_ONLY)
    assert ok[0] and not ok[4]
    assert world.stage_index(PAYER_ONLY) == 0


@pytest.mark.parametrize("seed", SEEDS)
def test_one_lock_order_passes_the_first_payout_run(seed):
    world, ok = first("reference", seed)
    assert ok == [True] * 5
    assert world.stage_index("reference") == 2  # One lock order


def test_reference_passes_every_goal_on_every_kind_of_incident():
    world = build_world("deadlock_avoidance", "reference", 10, seed=1)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 8 and {i.kind for i in run.incidents} == {"payout", "refunds", "slow", "batch"}
    assert all(all(r) for r in results), results


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("deadlock_avoidance", "reference", 7, params={"rate": 60.0})  # quieter: quicker
    run = world.runs["reference"]
    assert run.keys["transfers"] == sorted(run.keys["transfers"])
    assert run.keys["transfers"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference", rate=60.0), 7)
    asked = sum(len(p["tables"]["transfers"]) for p in pieces)
    assert run.total("asks", 1e9) == asked


def test_the_lock_manager_finds_a_cycle_and_a_timeout_breaks_it():
    locks = LockManager()

    async def hold_then_want(rid, first_, second, timeout):
        current_request.set(Request(rid))
        await locks.acquire(first_)
        await asyncio.sleep(0.01)
        try:
            await locks.acquire(second, timeout=timeout)
        except LockTimeout:
            return "timeout"
        finally:
            locks.release_request(rid)
        return "done"

    async def main():
        a = asyncio.ensure_future(hold_then_want(1, 10, 20, 0.5))
        b = asyncio.ensure_future(hold_then_want(2, 20, 10, None))
        await asyncio.sleep(0.1)
        found = locks.cycles()
        return found, await a, await b, locks.cycles()

    found, a, b, after = run_virtual(main())
    assert [sorted(accounts) for _, accounts in found] == [[10, 20]]
    assert (a, b) == ("timeout", "done") and after == []


# ------------------------------------------------------------- your code


def _service(rng_seed: int = 1):
    locks = LockManager(random.Random(rng_seed))
    ledger = Ledger(range(1, 30), random.Random(rng_seed + 1))
    audit = Audit(locks, random.Random(rng_seed + 2))
    return locks, ledger, audit, code.Payments(locks, ledger, audit, random.Random(rng_seed + 3))


def _as(rid: int, coro):
    """Run `coro` as transfer `rid` (its own task, its own request), releasing its locks after."""

    async def run(locks):
        current_request.set(Request(rid))
        try:
            return await coro
        finally:
            locks.release_request(rid)

    return run


@your_code(1, "backoff(attempt, rng) is full jitter, capped")
def test_stage1_backoff():
    rng = random.Random(7)
    waits = [code.backoff(a, rng) for a in range(1, 40) for _ in range(20)]
    assert all(0 <= w <= reference.CAP + 1e-9 for w in waits)
    first_waits = [code.backoff(1, rng) for _ in range(200)]
    assert max(first_waits) <= 0.02 + 1e-9 and len(set(first_waits)) > 100  # random, below BASE * 2
    assert code.backoff(5, random.Random(3)) == code.backoff(5, random.Random(3))


@your_code(1, "A pays B while B pays A: both finish, nothing waits forever")
def test_stage1_opposite_transfers_both_finish():
    async def main():
        locks, ledger, _, app = _service()
        a = asyncio.ensure_future(_as(1, app.transfer(3, 4, 100))(locks))
        b = asyncio.ensure_future(_as(2, app.transfer(4, 3, 50))(locks))
        await asyncio.wait_for(asyncio.gather(a, b), 5.0)
        return ledger.balances[3] - ledger.balances[4], ledger.drift

    diff, drift = run_virtual(main())
    assert diff == -100 and drift == 0


@your_code(1, "on a lock timeout, the locks already held are released before backing off")
def test_stage1_release_before_backing_off():
    assert code.LOCK_TIMEOUT is not None  # a lock wait must be able to give up
    timeout = float(code.LOCK_TIMEOUT)

    async def main():
        locks, _, _, app = _service()

        async def slow_holder():
            await locks.acquire(6)
            await asyncio.sleep(3 * timeout + 0.1)  # a GC pause while holding account 6

        async def other():
            await locks.acquire(5, timeout=2 * timeout)  # account 5 must come free meanwhile
            return True

        holder = asyncio.ensure_future(_as(9, slow_holder())(locks))
        await asyncio.sleep(0.005)
        transfer = asyncio.ensure_future(_as(1, app.transfer(5, 6, 10))(locks))  # gets 5, waits for 6
        await asyncio.sleep(0.02)
        try:
            got = await _as(2, other())(locks)
        except LockTimeout:
            got = False
        await asyncio.gather(holder, transfer, return_exceptions=True)
        return got

    assert run_virtual(main())


@your_code(1, "the first payout run: no deadlock lasts")
def test_stage1_first_incident_no_frozen_deadlock():
    world, ok = first(variant())
    assert ok[0] and ok[4]


@your_code(2, "lock_order(accounts): every account once, ascending")
def test_stage2_lock_order():
    assert list(code.lock_order([9, 4, 9, 2])) == [2, 4, 9]
    assert list(code.lock_order(a for a in (5, 1))) == [1, 5]


@your_code(2, "opposite transfers never wait for a timeout")
def test_stage2_opposite_transfers_need_no_timeout():
    async def main():
        locks, ledger, _, app = _service()
        reqs = [Request(1), Request(2)]

        async def go(req, src, dst):
            current_request.set(req)
            try:
                await app.transfer(src, dst, 10)
            finally:
                locks.release_request(req.rid)

        t0 = asyncio.get_running_loop().time()
        await asyncio.gather(go(reqs[0], 7, 8), go(reqs[1], 8, 7))
        return asyncio.get_running_loop().time() - t0, [r.timeouts for r in reqs], ledger.drift

    took, timeouts, drift = run_virtual(main())
    assert timeouts == [0, 0] and took < 0.1 and drift == 0


@your_code(2, "the audit log is written after the locks are released")
def test_stage2_audit_outside_the_locks():
    async def main():
        locks, _, audit, app = _service()
        await _as(1, app.transfer(3, 12, 10))(locks)
        await _as(2, app.settle([(3, -5), (12, -5), (2, 10)]))(locks)
        return audit.records, audit.locked

    records, locked = run_virtual(main())
    assert records == 2 and locked == 0


@your_code(2, "a batch locks all its accounts in id order before it moves anything")
def test_stage2_batch_locks_in_order_up_front():
    order = []

    async def main():
        locks, ledger, _, app = _service()
        acquire, apply = locks.acquire, ledger.apply

        async def spy_acquire(account, timeout=None):
            order.append(account)
            await acquire(account, timeout)

        async def spy_apply(entries):
            order.append("apply")
            await apply(entries)

        locks.acquire, ledger.apply = spy_acquire, spy_apply
        await _as(1, app.settle([(9, -1), (4, -1), (21, -1), (2, 3)]))(locks)

    run_virtual(main())
    assert order == [2, 4, 9, 21, "apply"]


@your_code(2, "the first payout run: every goal OK")
def test_stage2_first_incident_every_goal():
    world, ok = first(variant())
    assert ok == [True] * 5
    assert world.stage_index(variant()) == 2


def test_two_pictures_lanes_first():
    from live.canvas import RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v, at: float):
        world = build_world("deadlock_avoidance", v, 1)
        assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
        lanes = [adapter_for(world).frame(v, at + k / 5, 60) for k in range(40)]
        set_view(world, "cluster")
        frames = [adapter_for(world).frame(v, at + k / 5) for k in range(40)]
        assert all(len(f.nodes) == len(scenario.HOT) + 6 for f in frames)
        text = "\n".join(plain(line) for line in compose(world, v, at + 2, 92, 30))
        assert frames[10].state[0] in text  # the line under the grid fits the smallest screen
        return lanes, frames

    lanes, frames = picture(REQUEST_ORDER, 20.0)
    assert any(f.closed for f in lanes)  # every worker stuck: the door shuts
    assert RED in [c for f in frames for _, _, _, c in f.flights]  # a deadlock's cycle, in red
    assert RED in [c for f in frames for c in f.nodes]
    lanes, frames = picture("reference", 20.0)
    assert not any(f.closed for f in lanes)
    assert RED not in [c for f in frames for _, _, _, c in f.flights]
