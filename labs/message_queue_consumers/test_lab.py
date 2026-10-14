import asyncio
import itertools
import random

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import now, run_virtual
from labs.message_queue_consumers import reference as R
from labs.message_queue_consumers import scenario
from labs.message_queue_consumers.api import Broker, DeadLetters, Dlq, JobFailed, Queue

LAB = "message_queue_consumers"
code = load(LAB, variant(), (*scenario.NAMES, "backoff", "MAX_RECEIVES"))
# Goals: baseline, lost, duplicates, queue age, DLQ poison only


class ACK_AFTER:  # ack after the work, but no heartbeat: a job slower than the timeout is handed out twice
    class Consumer(R.Consumer):
        async def process(self, msg):
            try:
                await self.handle(msg)
            except JobFailed:
                return
            await self.queue.delete(msg)


class HEARTBEAT:  # stage 1: ack after the work and heartbeat while working; failures come back forever
    class Consumer(R.Consumer):
        async def process(self, msg):
            beat = asyncio.ensure_future(self.heartbeat(msg))
            try:
                await self.handle(msg)
            except JobFailed:
                return
            finally:
                beat.cancel()
            await self.queue.delete(msg)


class NO_BACKOFF:  # a DLQ, but failures are retried at once: four tries fit inside a short blip
    class Consumer(R.Consumer):
        async def on_failure(self, msg):
            if msg.receive_count >= R.MAX_RECEIVES:
                await self.dlq.send(msg)
                await self.queue.delete(msg)
            else:
                await self.queue.change_visibility(msg, 0)


class DLQ_NO_HEARTBEAT:  # retries and a DLQ, but no heartbeat: poison runs on two workers at once
    class Consumer(R.Consumer):
        async def process(self, msg):
            try:
                await self.handle(msg)
            except JobFailed:
                await self.on_failure(msg)
                return
            await self.queue.delete(msg)


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def by_kind(world, v) -> dict[str, list[list[bool]]]:
    run = world.runs[v]
    out: dict[str, list[list[bool]]] = {}
    for inc, result in zip(run.incidents, statuses(world, v)):
        out.setdefault(inc.kind, []).append(result)
    return out


# ------------------------------------------------------------- given behaviour


@starting_code
def test_starting_code_acks_on_receipt_and_loses_jobs():
    world = build_world(LAB, "main", 3)
    results = by_kind(world, "main")
    assert statuses(world, "main")[0] == [True, False, True, True, False]  # poison acked, then lost
    assert all(not r[1] for r in results["crash"] + results["blip"])  # crashes and blips lose jobs too
    assert world.stage_index("main") == 0  # Ack on receipt


def test_acking_after_the_work_without_a_heartbeat_works_slow_jobs_twice():
    for seed, minutes in ((1, 1), (5, 3), (6, 2)):
        world = build_world(LAB, ACK_AFTER, minutes, seed=seed)
        results = by_kind(world, ACK_AFTER)
        assert results["poison"][0] == [True, True, False, True, False]  # nothing lost, poison worked twice
        assert all(r[2] is False for r in results.get("slow", []))  # a slow downstream: slow jobs twice
        assert results.get("slow") or minutes == 1
        assert world.stage_index(ACK_AFTER) == 0
    world = build_world(LAB, DLQ_NO_HEARTBEAT, 1, seed=5)
    assert world.stage_index(DLQ_NO_HEARTBEAT) == 0  # a DLQ does not help without the heartbeat


def test_a_heartbeat_keeps_every_job_but_poison_never_leaves_the_queue():
    for seed in (1, 5, 6):
        world = build_world(LAB, HEARTBEAT, 1, seed=seed)
        assert statuses(world, HEARTBEAT)[0] == [True, True, True, True, False]
        assert world.stage_index(HEARTBEAT) == 1  # Ack after work
    # Four poison batches in a row: the poison going round eats the workers, and the queue backs up.
    world = build_world(LAB, HEARTBEAT, 5, seed=4)
    results = statuses(world, HEARTBEAT)
    assert [r[4] for r in results[:4]] == [False] * 4
    assert any(not r[3] for r in results[4:])  # queue age p99 over 1 s once the poison piles up


def test_retrying_at_once_parks_good_jobs_when_the_downstream_blips():
    world = build_world(LAB, NO_BACKOFF, 3, seed=1)
    assert world.stage_index(NO_BACKOFF) == 2  # the first incident (poison) passes ...
    blip = by_kind(world, NO_BACKOFF)["blip"][0]
    assert blip == [True, True, True, True, False]  # ... but a 1.6 s blip sends good jobs to the DLQ


def test_reference_passes_every_goal_for_ten_minutes():
    world = build_world(LAB, "reference", 10, seed=1)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 8 and {i.kind for i in run.incidents} == {"poison", "crash", "blip", "slow"}
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Retries + DLQ


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world(LAB, "reference", 7)
    run = world.runs["reference"]
    assert run.keys["jobs"] == sorted(run.keys["jobs"])
    assert run.keys["jobs"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    sent = sum(len(p["tables"]["jobs"]) for p in pieces)
    assert run.total("sent", 1e9) == sent


# ------------------------------------------------------------- your code


def _world(handle_time=0.1, fails=False):
    """A queue with one message, a consumer, and a handle that records what it saw."""
    broker = Broker()
    dead = DeadLetters()
    alive = [True]
    calls = {"handled": 0, "visibility": []}

    async def handle(msg):
        calls["handled"] += 1
        await asyncio.sleep(handle_time)
        if fails:
            raise JobFailed("bad payload")

    queue = Queue(broker, lambda: alive[0])
    real = queue.change_visibility

    async def change_visibility(msg, seconds):
        calls["visibility"].append((round(now(), 1), seconds))
        return await real(msg, seconds)

    queue.change_visibility = change_visibility
    consumer = code.Consumer(queue, Dlq(dead, lambda: alive[0]), handle, random.Random(1))
    broker.send({"order": 1})
    return broker, dead, consumer, calls, alive


@your_code(1, "the message is deleted only after the job succeeded; a crash mid-job leaves it in the queue")
def test_stage1_ack_after_the_work():
    async def main():
        broker, _, consumer, _, alive = _world(handle_time=1.0)
        msg = await broker.receive()
        task = asyncio.ensure_future(consumer.process(msg))
        await asyncio.sleep(0.5)
        still_there = msg.id in broker.records  # not acked while the job runs
        alive[0] = False  # the process crashes mid-job
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(5.0)
        again = await broker.receive()  # it comes back to another worker
        broker2, _, consumer2, _, _ = _world()
        msg2 = await broker2.receive()
        await consumer2.process(msg2)
        return still_there, again, msg2.id in broker2.records

    still_there, again, kept = run_virtual(main())
    assert still_there and again is not None and again.receive_count == 2
    assert not kept  # a job that succeeded is acked


@your_code(1, "a heartbeat keeps a slow job hidden while it runs, and stops when it ends")
def test_stage1_heartbeat_keeps_slow_jobs_hidden():
    async def main():
        broker, _, consumer, calls, _ = _world(handle_time=5.0)
        msg = await broker.receive()
        task = asyncio.ensure_future(consumer.process(msg))
        await asyncio.sleep(3.0)
        second = await broker.receive(wait=0.5)  # past the 2 s timeout: is it still hidden?
        await task
        n = len(calls["visibility"])
        await asyncio.sleep(5.0)
        return second, n, len(calls["visibility"]), msg.id in broker.records

    second, beats, later, kept = run_virtual(main())
    assert second is None  # no second worker got it
    assert beats >= 4  # extended every ~0.5 s for 5 s
    assert later == beats  # and the heartbeat stopped with the job
    assert not kept


@your_code(1, "the first incident (poison): no job lost, none worked on twice")
def test_stage1_first_incident_loses_nothing():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0][1:3] == [True, True]


@your_code(2, "backoff doubles from 1 s, is capped at 8 s, and keeps half of it fixed")
def test_stage2_backoff():
    rng = random.Random(3)
    for n, (low, high) in enumerate([(0.5, 1), (1, 2), (2, 4), (4, 8), (4, 8), (4, 8)], start=1):
        values = [code.backoff(n, rng) for _ in range(50)]
        assert all(low <= v <= high for v in values), (n, min(values), max(values))
        assert max(values) - min(values) > (high - low) / 4  # jittered


@your_code(2, "a failed job comes back later each time, and goes to the DLQ after MAX_RECEIVES")
def test_stage2_retries_then_dead_letter():
    async def main():
        broker, dead, consumer, calls, _ = _world(handle_time=0.05, fails=True)
        receives = []
        for _ in range(12):  # bounded: a message retried forever must not hang the test
            if not broker.records:
                break
            msg = await broker.receive(wait=10.0)
            if msg is None:
                break
            receives.append(round(now(), 1))
            await consumer.process(msg)
        return receives, dead.parked, calls["visibility"]

    receives, parked, hides = run_virtual(main())
    assert len(receives) == code.MAX_RECEIVES and parked == {0}
    gaps = [b - a for a, b in zip(receives, receives[1:])]
    assert gaps == sorted(gaps) and gaps[0] >= 0.5  # backing off, longer each time


@your_code(2, "poison goes to the DLQ: every goal OK on the first incident")
def test_stage2_first_incident_every_goal():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0] == [True] * 5
    assert world.stage_index(variant()) == 2


@starting_code
def test_two_pictures_the_cluster_first():
    from live.canvas import GREEN, PURPLE, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v: str, t: float):
        world = worlds[v]
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == 9
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert lanes.state[0] in text
        return frame, lanes

    worlds = {v: build_world(LAB, v, 1) for v in ("main", "reference")}
    assert views_for(worlds["main"]) == ["cluster", "lanes"] and worlds["main"].view == "cluster"  # cluster first
    # In the poison batch: the given code loses the poison (red); the reference parks it (purple).
    given = [picture("main", t) for t in (24.0, 27.0, 29.5)]
    solved = [picture("reference", t) for t in (32.0, 36.0, 40.0)]
    assert any(frame.drops for frame, _ in given)
    assert any(c == RED for _, lanes in given for c, _ in lanes.outcomes)
    assert any(dest == 5 and c == PURPLE for frame, _ in solved for _, dest, _, c in frame.flights)
    assert any(dest == 3 and c == GREEN for frame, _ in solved for _, dest, _, c in frame.flights)
    assert not any(frame.drops for frame, _ in solved)
