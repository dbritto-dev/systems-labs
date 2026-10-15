import asyncio
import itertools
from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import now, run_virtual
from labs.idempotency import scenario
from labs.idempotency.api import Conflict, KeyStore, Ledger, current_attempt

code = load("idempotency", variant(), scenario.NAMES)


class REMEMBER:  # stage 1 as most people first write it: look the key up, charge, store the receipt
    class PaymentService:
        def __init__(self, ledger, store):
            self.ledger, self.store = ledger, store

        async def charge(self, key, account, amount):
            seen = await self.store.get(key)
            if seen is not None:
                return seen
            receipt = {"charge_id": await self.ledger.insert(account, amount), "amount": amount}
            await self.store.set(key, receipt, 300.0)
            return receipt


class GLOBAL_LOCK:  # never a double charge, but one payment at a time: a slow ledger backs everyone up
    class PaymentService(REMEMBER.PaymentService):
        lock = None

        async def charge(self, key, account, amount):
            if self.lock is None:
                self.lock = asyncio.Lock()
            async with self.lock:
                return await super().charge(key, account, amount)


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_starting_code_charges_retried_payments_twice():
    world = build_world("idempotency", "main", 1)
    first = world.runs["main"].settled[0]
    assert [r.ok for r in first] == [True, False, False, False, True]
    assert world.stage_index("main") == 0  # No idempotency


def test_remembering_answers_replays_retries_but_races_on_slow_charges():
    world = build_world("idempotency", REMEMBER, 6)
    run = world.runs[REMEMBER]
    results = dict(zip((i.kind for i in run.incidents), statuses(world, REMEMBER)))
    assert results["slow"] == [True, True, False, False, True]  # the retry came while charging
    assert results["storm"] == [True, True, False, False, True]  # two tries at once both miss
    assert results["resets"] == [True] * 5  # answers lost after the charge: a replay is enough
    assert world.stage_index(REMEMBER) == 1  # Replays answers


def test_a_global_lock_never_charges_twice_but_is_slow_after_a_slow_ledger():
    world = build_world("idempotency", GLOBAL_LOCK, 1)
    first = world.runs[GLOBAL_LOCK].settled[0]
    assert [r.ok for r in first] == [True, True, True, True, False]
    assert world.stage_index(GLOBAL_LOCK) == 2


def test_reference_passes_every_goal_on_the_first_incidents():
    world = build_world("idempotency", "reference", 9)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 6 and {i.kind for i in run.incidents} == {"slow", "resets", "storm"}
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Reserved keys


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("idempotency", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["payments"] == sorted(run.keys["payments"])
    assert run.keys["payments"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    paid = sum(len(p["tables"]["payments"]) for p in pieces)
    assert run.total("pays", 1e9) == paid


# ------------------------------------------------------------- your code


def _service(latency=0.02):
    ledger = Ledger(latency)
    ledger.calls = 0

    def counted(who, charge_id):
        ledger.calls += 1

    ledger.on_charge = counted
    return code.PaymentService(ledger, KeyStore()), ledger


async def _charge(service, key, n=0):
    current_attempt.set((0, n))
    try:
        return await service.charge(key, 7, 1250)
    except Conflict:
        return "conflict"


@your_code(1, "a retry with the same key gets the stored receipt, without a second charge")
def test_stage1_sequential_retry_is_replayed():
    async def main():
        service, ledger = _service()
        first = await _charge(service, "k1")
        again = await _charge(service, "k1", 1)
        other = await _charge(service, "k2")
        return first, again, other, ledger.calls

    first, again, other, calls = run_virtual(main())
    assert first == again and first["amount"] == 1250
    assert other["charge_id"] != first["charge_id"]
    assert calls == 2  # k1 once, k2 once


@your_code(2, "two tries of one key at once charge once, and both get that receipt")
def test_stage2_concurrent_duplicates_charge_once():
    async def main():
        service, ledger = _service(latency=1.5)
        first = asyncio.ensure_future(_charge(service, "k1"))
        await asyncio.sleep(0.1)  # the retry comes while the first try is still charging
        second = asyncio.ensure_future(_charge(service, "k1", 1))
        answers = await asyncio.gather(first, second)
        later = await _charge(service, "k1", 2)
        return answers, later, ledger.calls

    (a, b), later, calls = run_virtual(main())
    assert calls == 1
    assert a == later and b in (a, "conflict")  # the duplicate waits for the receipt, or says 409


@your_code(2, "keys expire: the store does not grow forever")
def test_stage2_keys_expire():
    async def main():
        service, _ = _service()
        for i in range(20):
            await _charge(service, f"k{i}")
        full = len(service.store)
        await asyncio.sleep(24 * 3600)
        await _charge(service, "late")
        return full, len(service.store), now()

    full, left, _ = run_virtual(main())
    assert full == 20 and left == 1


@your_code(2, "no double charge on the first incident: every goal OK")
def test_stage2_first_incident_every_goal():
    world = build_world("idempotency", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first] == [True] * 5


@starting_code
def test_a_second_picture_shows_the_topology():
    from live.canvas import GREEN, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v: str):
        world = build_world("idempotency", v, 1)
        assert views_for(world) == ["relay", "cluster", "lanes"] and world.view == "relay"  # opens with relay
        set_view(world, "lanes")  # the checks below are about the lanes picture
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, 25.0)  # in the first incident: a slow ledger
        assert len(frame.nodes) == 3 and any(src == -1 for src, _, _, _ in frame.flights)
        text = "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        return frame

    given, solved = picture("main"), picture("reference")
    # Without keys, retries charge the ledger again (red); with them, receipts come from the key store.
    assert any(dest == 2 and colour == RED for _, dest, _, colour in given.flights)
    assert not any(colour == RED for _, _, _, colour in solved.flights)
    assert any(dest == 1 and colour == GREEN for _, dest, _, colour in solved.flights)


@starting_code
def test_the_relay_picture_shows_the_key_store():
    from live.canvas import GREEN, RED
    from live.views import adapter_for, set_view

    def relay(v: str):
        world = build_world("idempotency", v, 1)
        set_view(world, "relay")
        frame = adapter_for(world).frame(v, 27.0, 100)  # in the first incident: a slow ledger
        assert frame.users and frame.hops and frame.relay.label[0] and frame.state[0]
        return world, frame

    world, given = relay("main")
    # Without keys, retries reach the provider and charge again: red, and the provider says so.
    assert any(colour == RED for _, colour, _ in given.hops) and given.state == (world.s("state_double"), RED)
    world, solved = relay("reference")
    # With keys, the key store answers retries in the API (green) and nothing is charged twice.
    assert not any(colour == RED for _, colour, _ in solved.hops) and solved.relay.label[1] == GREEN
    assert any(colour == GREEN and k < 0.1 for k, colour, _ in solved.hops)
