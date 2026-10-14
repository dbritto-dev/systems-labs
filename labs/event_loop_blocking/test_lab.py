import asyncio
import itertools

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import now, run_virtual
from labs.event_loop_blocking import api, scenario
from labs.event_loop_blocking import reference as R
from labs.event_loop_blocking.api import CORES, DEFAULT_THREADS, Call, Overloaded, ProcessPool, ThreadPool, to_thread

LAB = "event_loop_blocking"
code = load(LAB, variant(), (*scenario.NAMES, "IO_THREADS", "CPU_PROCESSES", "IO_QUEUE", "CPU_QUEUE", "WATCH_EVERY"))
# Goals: loop lag p99 < 50 ms, health fails = 0, light p99 < 100 ms, heavy served ≥ 70%, queued ≤ 50,
# lag reported ≥ 90% of the seconds


class SYNC:  # stage 0, as given: every blocking call on the loop's thread
    class Service(R.Service):
        def __init__(self):
            self.io = self.cpu = self.watcher = None

        async def start(self):
            pass

        async def run_blocking(self, call):
            return call()


class TO_THREAD:  # stage 1: every blocking call to the default thread pool (8 threads, one GIL, no limit)
    class Service(R.Service):
        def __init__(self):
            self.io = self.cpu = self.watcher = None

        async def start(self):
            pass

        async def run_blocking(self, call):
            return await to_thread(call)


class HALF:  # blocking I/O to threads, but CPU work still on the loop
    class Service(TO_THREAD.Service):
        async def run_blocking(self, call):
            return call() if call.cpu else await to_thread(call)


class UNBOUNDED:  # the right pools and a watchdog, but no limit on their queues
    class Service(R.Service):
        async def offload(self, call):
            return await (self.cpu if call.cpu else self.io).run(call)


class ONE_POOL:  # bounded, watched, but CPU work in threads too: one GIL computes for everybody
    class Service(R.Service):
        def __init__(self):
            super().__init__()
            self.cpu = self.io


class NO_WATCHDOG:  # bounded pools per kind of work, but nobody measures the loop's lag
    class Service(R.Service):
        async def start(self):
            pass


class BROKEN:  # a bug in the code under test
    class Service(R.Service):
        async def run_blocking(self, call):
            raise KeyError("oops")


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def first_values(world, v):
    return [r.value for r in world.runs[v].settled[0]]


# ------------------------------------------------------------- given behaviour


def test_the_first_incident_is_an_upload_batch_at_0_20():
    for seed in (1, 2, 99):
        first = next(scenario.incidents(seed))
        assert (first.t0, first.t1, first.kind) == (20.0, 50.0, "uploads")
    incs = list(itertools.islice(scenario.incidents(3), 40))
    assert {i.kind for i in incs} == {"uploads", "slow_dep", "reports", "gc"} and all(i.cause for i in incs)
    gaps = [b.t0 - a.t1 for a, b in zip(incs, incs[1:])]
    assert min(gaps) >= scenario.QUIET


def test_a_blocking_call_stops_every_task_on_the_loop():
    async def main():
        ticks = []

        async def ticker():
            while True:
                ticks.append(now())
                await asyncio.sleep(0.01)

        task = asyncio.ensure_future(ticker())
        await asyncio.sleep(0.05)
        Call("resize", 0.5, True)()  # on the loop: nothing else runs for 0.5 s
        await asyncio.sleep(0.05)
        task.cancel()
        return max(b - a for a, b in zip(ticks, ticks[1:]))

    assert run_virtual(main()) >= 0.5


def test_threads_take_turns_on_the_gil_and_processes_do_not():
    async def burst(pool_or_none, cpu: bool):
        t = now()
        calls = [Call("resize" if cpu else "db", 1.0, cpu) for _ in range(4)]
        if pool_or_none is None:
            await asyncio.gather(*(to_thread(c) for c in calls))
        else:
            await asyncio.gather(*(pool_or_none.run(c) for c in calls))
        return now() - t

    async def main():
        return (await burst(None, cpu=True), await burst(None, cpu=False),
                await burst(ProcessPool(CORES), cpu=True), await burst(ThreadPool(2), cpu=False))

    gil, io, procs, two = run_virtual(main())
    assert gil == pytest.approx(4.0, abs=0.05)  # 8 threads, one GIL: one at a time
    assert io == pytest.approx(1.0, abs=0.05)  # blocking I/O releases the GIL: all at once
    assert procs == pytest.approx(1.0, abs=0.05)  # 4 processes, 4 cores
    assert two == pytest.approx(2.0, abs=0.05)  # 2 threads: two rounds
    assert DEFAULT_THREADS == min(32, CORES + 4)


def test_the_loop_slows_down_while_a_thread_computes():
    async def main():
        t = now()
        api.block(0.01)
        alone = now() - t
        job = asyncio.ensure_future(to_thread(Call("report", 1.0, True)))
        await asyncio.sleep(0)
        t = now()
        api.block(0.01)
        shared = now() - t
        await job
        return alone, shared

    alone, shared = run_virtual(main())
    assert alone == pytest.approx(0.01) and shared == pytest.approx(0.01 * api.GIL_SHARE)


def test_blocking_calls_on_the_loop_get_the_instance_killed():
    for seed in (1, 2, 3):
        world = build_world(LAB, SYNC, 1, seed=seed)
        assert statuses(world, SYNC)[0][:3] == [False, False, False]  # lag, health checks, light p99
        assert world.stage_index(SYNC) == 0  # Sync calls on the loop
        assert world.runs[SYNC].rows("kills", 20.0, 50.0)  # killed during the upload batch
        assert world.runs[SYNC].total("failed", 60) > 1000


def test_cpu_on_the_loop_is_still_blocking():
    world = build_world(LAB, HALF, 1)
    assert world.stage_index(HALF) == 0


def test_to_thread_frees_the_loop_but_the_queue_grows():
    for seed in (1, 2, 3):
        world = build_world(LAB, TO_THREAD, 1, seed=seed)
        lag, health, light, served, queued, watched = statuses(world, TO_THREAD)[0]
        assert lag and health and light  # the loop stays responsive ...
        assert not served and not queued  # ... but one GIL for 5 cores of resizing: hundreds queue up
        assert world.stage_index(TO_THREAD) == 1  # Offloaded to threads
        assert int(first_values(world, TO_THREAD)[4]) > 300


def test_each_missing_piece_of_stage_2_keeps_you_at_stage_1():
    for seed in (1, 2):
        for v, failing in ((UNBOUNDED, "queued"), (ONE_POOL, "served"), (NO_WATCHDOG, "watched")):
            world = build_world(LAB, v, 1, seed=seed)
            keys = [g.key for g in world.goals]
            result = dict(zip(keys, statuses(world, v)[0]))
            assert not result[failing], (v.__name__, result)
            assert result["lag"] and result["health"]
            assert world.stage_index(v) == 1, v.__name__


def test_reference_passes_every_goal_for_ten_minutes():
    kinds = set()
    for seed in (1, 4):
        world = build_world(LAB, "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 4 and all(all(r) for r in results), results
        kinds |= {i.kind for i in world.runs["reference"].incidents}
        assert world.stage_index("reference") == 2  # Bounded executors
        assert not world.runs["reference"].rows("kills", 0, 600)
    assert kinds == {"uploads", "slow_dep", "reports", "gc"}


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world(LAB, "reference", 7)
    run = world.runs["reference"]
    keys = run.keys["requests"]
    assert keys == sorted(keys) and keys[0] >= 60  # minute 0 is gone
    pieces = list(itertools.islice(scenario.stream("reference"), 7))
    assert run.total("served", 1e9) + run.total("failed", 1e9) == sum(len(p["tables"]["requests"]) for p in pieces)
    assert all(a < b for a, b in zip(run.keys["lags"], run.keys["lags"][1:]))


def test_a_kill_loses_what_was_in_flight_and_a_new_service_starts():
    made = []

    class COUNTED:
        class Service(TO_THREAD.Service):
            def __init__(self):
                super().__init__()
                made.append(self)

    class COUNTED_MAIN:
        class Service:
            def __init__(self):
                made.append(self)

            async def start(self):
                pass

            async def run_blocking(self, call):
                return call()

    piece = scenario.run(COUNTED_MAIN, chunk=0)
    kills = piece["tables"]["kills"]
    assert kills and len(made) == 1 + sum(1 for k in kills if k[1] < 60 + scenario.DRAIN)
    outcomes = {r[5] for r in piece["tables"]["requests"]}
    assert {scenario.KILLED, scenario.DOWN} <= outcomes
    made.clear()
    scenario.run(COUNTED, chunk=0)
    assert len(made) == 1  # offloaded: never killed


def test_a_bug_in_your_code_is_reported():
    with pytest.raises(KeyError, match="oops"):
        scenario.run(BROKEN, chunk=0)


# ------------------------------------------------------------- your code


def _service():
    return code.Service()


@your_code(1, "run_blocking keeps the loop free while a call runs")
def test_stage1_the_loop_keeps_running():
    async def main():
        s = _service()
        await s.start()
        ticks = []

        async def ticker():
            while True:
                ticks.append(now())
                await asyncio.sleep(0.01)

        task = asyncio.ensure_future(ticker())
        await asyncio.sleep(0.02)
        result = await s.run_blocking(Call("resize", 0.5, True, result="thumb.jpg"))
        await asyncio.sleep(0.05)
        task.cancel()
        return result, max(b - a for a, b in zip(ticks, ticks[1:]))

    result, gap = run_virtual(main())
    assert result == "thumb.jpg"
    assert gap < 0.05


@your_code(1, "the first incident (an upload batch): no health check fails")
def test_stage1_first_incident_no_kill():
    world = build_world(LAB, variant(), 1)
    lag, health, *_ = statuses(world, variant())[0]
    assert lag and health
    assert world.stage_index(variant()) >= 1


@your_code(2, "CPU work runs on CPU_PROCESSES processes at once, blocking I/O on IO_THREADS threads")
def test_stage2_each_kind_on_its_pool():
    async def main():
        s = _service()
        await s.start()
        t = now()
        await asyncio.gather(*(s.run_blocking(Call("resize", 1.0, True)) for _ in range(code.CPU_PROCESSES)))
        cpu = now() - t
        t = now()
        await asyncio.gather(*(s.run_blocking(Call("db", 1.0, False)) for _ in range(code.IO_THREADS)))
        return cpu, now() - t

    cpu, io = run_virtual(main())
    assert cpu < 1.2  # in parallel, out of the GIL (not 4 s)
    assert io < 1.2


@your_code(2, "a full queue answers Overloaded at once")
def test_stage2_bounded_queue():
    async def main():
        s = _service()
        await s.start()
        n = code.CPU_PROCESSES + code.CPU_QUEUE + 3
        t = now()
        results = await asyncio.gather(*(s.run_blocking(Call("report", 1.0, True)) for _ in range(n)),
                                       return_exceptions=True)
        refused = [r for r in results if isinstance(r, Overloaded)]
        io = await asyncio.gather(*(s.run_blocking(Call("db", 0.1, False)) for _ in range(5)))
        return len(refused), now() - t, io

    refused, _, io = run_virtual(main())
    assert refused == 3
    assert len(io) == 5  # a full CPU queue does not refuse I/O: two bulkheads


@your_code(2, "the watchdog reports the loop's lag every WATCH_EVERY seconds")
def test_stage2_watchdog_reports():
    async def main():
        s = _service()
        await s.start()
        await asyncio.sleep(1.0)
        api.block(0.3)  # the loop is held 0.3 s
        await asyncio.sleep(1.0)
        return list(api.runtime().reports)

    reports = run_virtual(main())
    assert 15 <= len(reports) <= 25
    lags = [lag for _, lag in reports]
    assert max(lags) == pytest.approx(0.3, abs=code.WATCH_EVERY + 0.01)
    assert sorted(lags)[len(lags) // 2] < 0.01  # mostly on time


@your_code(2, "every goal OK on the first incident")
def test_stage2_first_incident_every_goal():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0] == [True] * 6
    assert world.stage_index(variant()) == 2


# ------------------------------------------------------------- the pictures


def test_two_pictures_the_lanes_first():
    from live.canvas import PURPLE, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for
    from live.worlds.event_loop_blocking import CPU_C, GIL_C

    worlds = {"sync": build_world(LAB, SYNC, 1),
              "reference": build_world(LAB, "reference", 1), "stage1": build_world(LAB, TO_THREAD, 1)}
    assert views_for(worlds["sync"]) == ["lanes", "cluster"] and worlds["sync"].view == "lanes"

    def pictures(key, v, t: float):
        world = worlds[key]
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        assert lanes.state[0] in "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert len(lanes.state[0]) <= 15
        set_view(world, "cluster")
        cluster = adapter_for(world).frame(v, t)
        assert cluster.state[0] in "\n".join(plain(line) for line in compose(world, v, t, 110, 44))
        return lanes, cluster

    run = worlds["sync"].runs[SYNC]
    kill = run.rows("kills", 20.0, 50.0)[0]
    lanes, cluster = pictures("sync", SYNC, kill[0] + 2)  # killed: the door is shut, the loop dark
    assert lanes.closed and lanes.state[1] == RED and len(cluster.nodes) == 1
    stalls = [b for b in run.rows("blocks", 20.0, kill[0]) if b[1] - b[0] > 0.2]
    lanes, cluster = pictures("sync", SYNC, stalls[0][0] + 0.15)  # a resize on the loop: blocked
    assert not lanes.closed and lanes.state[1] == RED and lanes.fill == 1.0 and cluster.nodes[0] == RED
    for t in (30.0, 45.0):
        lanes, cluster = pictures("reference", "reference", t)  # four processes compute at once
        assert not lanes.closed and lanes.state[1] != RED
        assert len(cluster.nodes) == 1 + R.IO_THREADS + R.CPU_PROCESSES
        assert sum(1 for c in cluster.nodes if c == CPU_C) >= 3
        lanes, cluster = pictures("stage1", TO_THREAD, t)  # eight threads, one GIL
        assert len(cluster.nodes) == 1 + DEFAULT_THREADS
        assert sum(1 for c in cluster.nodes[1:] if c == CPU_C) <= 1  # one computes ...
        assert sum(1 for c in cluster.nodes[1:] if c == GIL_C) >= 5  # ... the rest wait for the GIL
        assert PURPLE not in cluster.nodes
