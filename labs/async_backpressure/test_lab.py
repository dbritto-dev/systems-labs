import asyncio
import itertools

import pytest

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import now, run_virtual
from labs.async_backpressure import main, reference, scenario
from labs.async_backpressure.api import (
    BASE_MEMORY, ENRICHED, HIGH, LOW, MAX_BATCH, MEMORY_LIMIT, RAW, SIZE, UPSTREAM_MAX, Enricher, Event,
    Firehose, Killed, Services, Sink, write_time,
)

code = load("async_backpressure", variant(), scenario.NAMES)
SEEDS = (1, 2, 3)
OOM, LOST, PEAK, THROUGHPUT, P99 = 1, 2, 3, 4, 5  # goal positions after the baseline


class BOUNDED:  # stage 1: asyncio.Queue(maxsize=QUEUE_SIZE), writes of 50
    class Pipeline(main.Pipeline):
        def __init__(self, io):
            super().__init__(io)
            self.to_a, self.to_b, self.to_c = (asyncio.Queue(maxsize=main.QUEUE_SIZE) for _ in range(3))


class BOUNDED_ADAPTIVE:  # bounded queues and adaptive writes, but the source only pauses
    class Pipeline(BOUNDED.Pipeline):
        async def writer(self):
            while True:
                await reference.write(self.io, await reference.take_batch(self.to_c, MAX_BATCH))


class NO_SHED:  # credits and adaptive batches, but `admit` lets everything in: the source only pauses
    class Pipeline(reference.Pipeline):
        def admit(self, chunk):
            return chunk


class FIXED_BATCH:  # credits and shedding, but still writes of 50
    class Pipeline(reference.Pipeline):
        async def writer(self):
            while True:
                batch = []
                while len(batch) < reference.BATCH:
                    batch += await self.to_c.get()
                await reference.write(self.io, batch)
                self.credits_c.grant(len(batch))


class UNBOUNDED_ADAPTIVE:  # adaptive writes on unbounded queues: the backlog still grows in memory
    class Pipeline(main.Pipeline):
        async def writer(self):
            while True:
                await reference.write(self.io, await reference.take_batch(self.to_c, MAX_BATCH))


def first(v, seed=1):
    world = build_world("async_backpressure", v, 2, seed=seed)  # the first incident settles at ~1:05
    return world, [r.ok for r in world.runs[v].settled[0]]


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", SEEDS)
@starting_code
def test_unbounded_queues_grow_until_the_process_is_oom_killed(seed):
    world, ok = first("main", seed)
    assert ok[0] and not ok[OOM] and not ok[LOST] and not ok[PEAK] and not ok[THROUGHPUT]
    assert world.stage_index("main") == 0  # Unbounded queues


@pytest.mark.parametrize("seed", SEEDS)
@starting_code
def test_bounded_queues_stop_the_oom_but_the_upstream_overflows(seed):
    world, ok = first(BOUNDED, seed)
    assert ok[OOM] and ok[PEAK] and not ok[LOST] and not ok[THROUGHPUT]
    assert world.stage_index(BOUNDED) == 1  # Bounded queues


@pytest.mark.parametrize("seed", SEEDS[:2])
@starting_code
def test_adaptive_batches_alone_keep_up_better_but_pausing_still_loses_events(seed):
    for v in (BOUNDED_ADAPTIVE, NO_SHED):
        world, ok = first(v, seed)
        assert ok[OOM] and ok[PEAK] and ok[THROUGHPUT] and not ok[LOST]
        assert world.stage_index(v) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_credits_with_fixed_batches_waste_the_slow_sink(seed):
    world, ok = first(FIXED_BATCH, seed)
    assert ok[OOM] and ok[PEAK] and not ok[THROUGHPUT]
    assert world.stage_index(FIXED_BATCH) == 1


@starting_code
def test_adaptive_batches_on_unbounded_queues_still_run_out_of_memory():
    world, ok = first(UNBOUNDED_ADAPTIVE)
    assert not ok[PEAK]
    assert world.stage_index(UNBOUNDED_ADAPTIVE) == 0


@pytest.mark.parametrize("seed", (1, 5))
def test_reference_passes_every_goal_on_every_kind_of_incident(seed):
    world = build_world("async_backpressure", "reference", 9, seed=seed)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 6 and {i.kind for i in run.incidents[:len(results)]} == {"slow", "spike", "burst",
                                                                                     "outage"}
    assert all(all(r) for r in results), results
    assert world.stage_index("reference") == 2  # Credits + adaptive batches


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("async_backpressure", "reference", 7, params={"rate": 500.0})  # quieter: quicker
    run = world.runs["reference"]
    assert run.keys["ticks"] == sorted(run.keys["ticks"]) and run.keys["events"] == sorted(run.keys["events"])
    assert run.keys["ticks"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference", rate=500.0), 7)
    arrived = sum(r[1] for p in pieces for r in p["tables"]["ticks"])
    assert run.total("arrived", 1e9) == arrived


def _events(n, priority=LOW, start=1):
    return [Event(start + i, 0.0, priority) for i in range(n)]


def test_memory_counts_every_event_held_and_the_kill_is_at_the_limit():
    async def main_():
        hose = Firehose()
        io = Services(hose, Enricher(), Sink())
        hose.push(_events(40))
        chunk = await io.read()
        raw = io.memory
        parsed = io.parse(chunk)
        enriched = await io.enrich(parsed)
        held = io.memory
        await io.write(enriched)
        return chunk, raw, held, io.memory

    chunk, raw, held, after = run_virtual(main_())
    assert len(chunk) == 40 and raw == BASE_MEMORY + 40 * SIZE[RAW]
    assert held == BASE_MEMORY + 40 * SIZE[ENRICHED] and after == BASE_MEMORY

    async def flood():
        hose = Firehose()
        io = Services(hose, Enricher(), Sink())
        room = (MEMORY_LIMIT - BASE_MEMORY) // SIZE[RAW]
        for k in range(room // 50 + 2):
            hose.push(_events(50, start=1 + 50 * k))
            try:
                await io.read()
            except Killed:
                return io, k * 50
        return io, None

    io, at = run_virtual(flood())
    assert not io.alive and at == (MEMORY_LIMIT - BASE_MEMORY) // SIZE[RAW] // 50 * 50
    assert io.peak > MEMORY_LIMIT


def test_the_upstream_keeps_only_its_buffer_and_drops_the_oldest():
    dropped = []
    hose = Firehose(on_lost=dropped.extend)
    hose.push(_events(UPSTREAM_MAX + 300))
    assert len(hose.buffer) == UPSTREAM_MAX and [e.id for e in dropped] == list(range(1, 301))


def test_the_sink_runs_one_write_at_a_time_and_batches_amortise_its_overhead():
    async def main_():
        sink = Sink()
        sink.slow = 16.0
        t = now()
        await asyncio.gather(sink.call(50), sink.call(50))
        return now() - t

    assert run_virtual(main_()) == pytest.approx(2 * write_time(50, 16.0))
    assert MAX_BATCH / write_time(MAX_BATCH, 16) > 3 * 50 / write_time(50, 16)


# ------------------------------------------------------------- your code


async def _slow_sink_run(pipeline_cls, seconds=25.0):
    """Feed a pipeline 1,000 events/s while the sink is 16x slower; return its io."""
    hose = Firehose()
    sink = Sink()
    sink.slow = 16.0
    io = Services(hose, Enricher(), sink)
    task = asyncio.ensure_future(pipeline_cls(io).run())
    ids = itertools.count(1)
    end = now() + seconds
    while now() < end and io.alive:
        await asyncio.sleep(0.01)
        hose.push([Event(next(ids), now(), HIGH if k % 3 == 0 else LOW) for k in range(10)])
    task.cancel()
    return io


@your_code(1, "bounded queues: a slow sink makes the source wait; memory stays flat")
def test_stage1_a_slow_sink_does_not_kill_the_process():
    io = run_virtual(_slow_sink_run(code.Pipeline))
    assert io.alive and io.peak <= 0.8 * MEMORY_LIMIT


@your_code(1, "the first incident: no OOM kill, memory under 80%")
def test_stage1_first_incident_no_oom():
    _, ok = first(variant())
    assert ok[OOM] and ok[PEAK]


@your_code(2, "Credits: a window of permits, served first come first served")
def test_stage2_credits():
    async def main_():
        c = code.Credits(10)
        assert c.free == 10 and c.try_take(4) and c.free == 6 and not c.try_take(7) and c.free == 6
        order = []

        async def taker(name, n):
            await c.take(n)
            order.append(name)

        big = asyncio.ensure_future(taker("big", 8))
        await asyncio.sleep(0)
        assert not c.try_take(1)  # someone is waiting: no jumping the queue
        small = asyncio.ensure_future(taker("small", 1))
        await asyncio.sleep(0)
        c.grant(1)  # 7 free: not enough for big, and small waits behind it
        await asyncio.sleep(0)
        assert order == []
        c.grant(3)  # 10 free: big, then small
        await asyncio.gather(big, small)
        assert order == ["big", "small"] and c.free == 1
        c.grant(9)
        await asyncio.wait_for(c.take(50), 1.0)  # more than the window: takes the whole window
        return c.free

    assert run_virtual(main_()) == 0


@your_code(2, "take_batch: one chunk, then what is queued, at most `most`")
def test_stage2_take_batch():
    async def main_():
        q = asyncio.Queue()
        later = asyncio.ensure_future(code.take_batch(q, 100))
        await asyncio.sleep(0.5)
        assert not later.done()  # waits for the first chunk
        q.put_nowait(_events(10))
        first_ = await later
        for k in range(5):
            q.put_nowait(_events(30, start=100 + 30 * k))
        second = await code.take_batch(q, 100)
        third = await code.take_batch(q, 100)
        return first_, second, third, q.qsize()

    first_, second, third, left = run_virtual(main_())
    assert len(first_) == 10 and len(second) == 100 and len(third) == 50 and left == 0
    assert len({e.id for e in second + third}) == 150  # nothing lost, nothing twice


@your_code(2, "admit: LOW is shed (counted) when the window is short, HIGH never")
def test_stage2_admit_sheds_only_low():
    async def main_():
        io = Services(Firehose(), Enricher(), Sink())
        p = code.Pipeline(io)
        hose = io._firehose
        hose.push(_events(30, LOW) + _events(20, HIGH, start=100))
        chunk = await io.read()
        assert p.admit(chunk) == chunk and io.shed_count == 0  # plenty of room: everything
        p.credits_a.try_take(p.credits_a.free - 10)  # the window is nearly full
        kept = p.admit(chunk)
        return kept, io.shed_count

    kept, shed = run_virtual(main_())
    assert {e.priority for e in kept} == {HIGH} and len(kept) == 20 and shed == 30


@your_code(2, "credits: a long slow sink sheds LOW, keeps memory low and writes every HIGH")
def test_stage2_slow_sink_sheds_low_and_writes_high():
    io = run_virtual(_slow_sink_run(code.Pipeline, 40.0))
    assert io.alive and io.peak <= 0.8 * MEMORY_LIMIT and io.shed_count > 0
    assert len(io._firehose.buffer) < UPSTREAM_MAX  # the upstream never overflowed


@your_code(2, "the first incident: every goal OK")
def test_stage2_first_incident_every_goal():
    world, ok = first(variant())
    assert ok == [True] * 6
    assert world.stage_index(variant()) == 2


@starting_code
def test_the_lanes_and_cluster_pictures():
    from live.canvas import MUTED, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v, a, b):
        world = build_world("async_backpressure", v, 1)
        assert views_for(world) == ["pipeline", "cluster", "lanes"] and world.view == "pipeline"  # opens with it
        set_view(world, "lanes")  # the checks below are about the lanes and cluster pictures
        times = [a + k * (b - a) / 40 for k in range(40)]
        lanes = [adapter_for(world).frame(v, t, 60) for t in times]
        set_view(world, "cluster")
        frames = [adapter_for(world).frame(v, t) for t in times]
        assert all(len(f.nodes) == 5 and f.columns == 5 and len(f.labels) == 5 for f in frames)
        text = "\n".join(plain(line) for line in compose(world, v, a, 92, 30))
        assert frames[0].state[0] in text  # the line under the row fits the smallest screen
        return lanes, frames

    given_lanes, given = picture("main", 26.0, 36.0)  # the OOM kill
    assert any(f.fill > 0.8 for f in given_lanes)  # the memory gauge climbs past 80%
    assert RED in [c for f in given_lanes for c, _ in f.outcomes]  # events lost at the door
    assert any(f.closed for f in given_lanes)  # the restart: the door is shut
    assert any(f.drops for f in given)  # lost inside the pipeline
    ref_lanes, _ = picture("reference", 25.0, 35.0)
    assert MUTED in [c for f in ref_lanes for c, _ in f.outcomes]  # LOW events shed at the door
    assert all(f.fill < 0.8 for f in ref_lanes) and RED not in [c for f in ref_lanes for c, _ in f.outcomes]


@starting_code
def test_the_pipeline_picture_shows_memory_piling_up_in_front_of_the_slow_sink():
    from live.canvas import EXTRA2, MUTED, RED, plain
    from live.frame import compose
    from live.views import adapter_for

    def frames(v):
        world = build_world("async_backpressure", v, 1)
        assert world.view == "pipeline"
        out = [adapter_for(world).frame(v, 20.0 + k * 0.1, 60) for k in range(160)]  # the slow sink
        assert all(len(f.boxes) == 4 for f in out)  # A parse, B enrich, C write, the sink
        text = "\n".join(plain(line) for line in compose(world, v, 30.0, 92, 30))
        assert out[100].state[0] in text and "C " in text  # the state and the names fit the smallest screen
        return out

    given = frames("main")
    # The starting code reads everything: stage C (in front of the slow sink) fills, every box turns
    # orange above 80% of the memory, then red: the OOM kill. Its events die where they were, the door
    # shuts red while the process restarts and events pile up upstream (the users).
    assert max(f.boxes[2].fill for f in given) > 0.8
    assert any(f.boxes[0].outline == EXTRA2 for f in given) and any(f.boxes[0].outline == RED for f in given)
    assert any(f.drops for f in given) and any(f.closed and f.door_color == RED for f in given)
    assert any(len(f.users) > 10 for f in given)
    solved = frames("reference")
    # The reference bounds its queues and sheds LOW events: C stays low, nothing turns red, and the
    # shed events fly back to the door in grey.
    assert max(f.boxes[2].fill for f in solved) < 0.5
    assert not any(f.drops for f in solved) and not any(b.outline == RED for f in solved for b in f.boxes)
    assert any(back and colour == MUTED for f in solved for _, _, colour, back in f.hops)
    assert MUTED in [c for f in solved for c, _ in f.outcomes]
