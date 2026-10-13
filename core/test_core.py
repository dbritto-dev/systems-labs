import asyncio
import random
import time

import pytest

from core import contract
from core.services import (
    DatabaseBusy,
    FaultyService,
    ServiceError,
    SlowDatabase,
    current_request,
)
from core.vtime import run_virtual


def test_sleep_an_hour_returns_instantly():
    async def main():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.sleep(3600)
        return loop.time() - t0

    wall = time.perf_counter()
    assert run_virtual(main()) == pytest.approx(3600)
    assert time.perf_counter() - wall < 0.5


def test_timeout_and_call_later_work():
    async def main():
        loop = asyncio.get_running_loop()
        fired = []
        loop.call_later(5, lambda: fired.append(loop.time()))
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(2):
                await asyncio.sleep(10)
        assert loop.time() == pytest.approx(2)
        await asyncio.sleep(4)
        return fired

    assert run_virtual(main()) == [pytest.approx(5)]


def test_many_tasks_interleave_in_time_order():
    async def worker(i, out):
        await asyncio.sleep(i * 0.5)
        out.append((asyncio.get_running_loop().time(), i))

    async def main():
        out = []
        await asyncio.gather(*(worker(i, out) for i in (3, 1, 2, 0)))
        return out

    assert [i for _, i in run_virtual(main())] == [0, 1, 2, 3]


def test_deadlock_is_reported_not_hung():
    async def main():
        await asyncio.get_running_loop().create_future()

    with pytest.raises(RuntimeError, match="wait forever"):
        run_virtual(main())


def _simulate(seed):
    async def one(svc, rid):
        current_request.set(rid)
        try:
            await svc.call()
        except ServiceError:
            pass

    async def main():
        rng = random.Random(seed)
        svc = FaultyService(error_rate=0.2, rng=random.Random(seed))
        tasks = []
        for rid in range(200):
            await asyncio.sleep(rng.expovariate(100))
            if rid == 50:
                svc.set_down(True)
            if rid == 80:
                svc.set_down(False)
            tasks.append(asyncio.ensure_future(one(svc, rid)))
        await asyncio.gather(*tasks)
        return svc.events

    return run_virtual(main())


def test_same_seed_same_events():
    a, b = _simulate(7), _simulate(7)
    assert a == b
    assert a != _simulate(8)
    assert {e.kind for e in a} == {"call", "ok", "error"}


def test_attempts_are_counted_per_request():
    async def main():
        svc = FaultyService()
        svc.set_down(True)
        current_request.set(9)
        for _ in range(3):
            with pytest.raises(ServiceError):
                await svc.call()
        return [e.attempt for e in svc.events if e.kind == "call"]

    assert run_virtual(main()) == [0, 1, 2]


def test_slow_database_queues_beyond_its_concurrency():
    async def main():
        db = SlowDatabase(service_time=0.02, concurrency=8, queue_limit=4)
        results = await asyncio.gather(*(db.read(i) for i in range(16)), return_exceptions=True)
        return asyncio.get_running_loop().time(), results

    t, results = run_virtual(main())
    busy = [r for r in results if isinstance(r, DatabaseBusy)]
    assert len(busy) == 4  # 8 running, 4 queued, 4 rejected
    assert t == pytest.approx(0.04)


def test_contract_names_missing_names(tmp_path):
    f = tmp_path / "mine.py"
    f.write_text("class Clinet: pass\n")
    with pytest.raises(ImportError, match=r"'Client' \(found 'Clinet': a typo\?\)"):
        contract.load("retry_storm", str(f), ["Client"])


def test_params_are_validated():
    meta = {"id": "x", "params": {"rate": contract.Param(100.0), "n": contract.Param(3)}}
    assert contract.parse_params(meta, ["rate=50", "n=4"]) == {"rate": 50.0, "n": 4}
    with pytest.raises(ValueError, match="must be a number"):
        contract.parse_params(meta, ["rate=fast"])
    with pytest.raises(ValueError, match="Did you mean 'rate'"):
        contract.parse_params(meta, ["rat=1"])
    with pytest.raises(ValueError, match="name=value"):
        contract.parse_params(meta, ["rate"])


def test_a_virtual_run_steps_forward_and_keeps_its_state():
    from core.vtime import VirtualRun

    ticks = []

    async def clock():
        while True:
            ticks.append(asyncio.get_running_loop().time())
            await asyncio.sleep(10)

    sim = VirtualRun()
    sim.spawn(clock())
    sim.run_until(60)
    assert sim.now == 60 and len(ticks) == 7  # 0, 10, ..., 60: timers due at t run too
    sim.run_until(125)
    assert len(ticks) == 13 and ticks[-1] == 120  # the same loop went on
    sim.close()


def test_a_bug_in_a_background_task_is_raised():
    from core.vtime import VirtualRun

    async def bug():
        await asyncio.sleep(5)
        raise KeyError("oops")

    sim = VirtualRun()
    sim.spawn(bug())
    with pytest.raises(KeyError):
        sim.run_until(10)
    sim.close()


def test_traffic_drifts_but_averages_out():
    import itertools as it

    from core.incidents import arrivals, rate_at

    rates = [rate_at(100, t, 1) for t in range(0, 900, 5)]
    assert 80 < min(rates) < 95 and 105 < max(rates) < 120
    times = list(it.takewhile(lambda t: t < 600, arrivals(100, 1, 0.0, random.Random(1))))
    assert 55_000 < len(times) < 65_000
