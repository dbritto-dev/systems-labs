import asyncio
import itertools
import random
from collections import deque

import pytest

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import run_virtual
from labs.connection_pool import scenario
from labs.connection_pool.scenario import Database

code = load("connection_pool", variant(), scenario.NAMES)


class PoolTimeout(Exception):
    pass


class ConnectEach:  # stage 0: a new connection per request
    def __init__(self, db, max_size=20, timeout=0.5):
        self.db = db

    async def acquire(self):
        return await self.db.connect()

    def release(self, conn):
        conn.close()


class Unbounded:  # stage 1: reuse, but no cap
    def __init__(self, db, max_size=20, timeout=0.5):
        self.db, self.idle = db, []

    async def acquire(self):
        return self.idle.pop() if self.idle else await self.db.connect()

    def release(self, conn):
        self.idle.append(conn)


class Bounded:  # stage 2: capped, waits for as long as it takes
    def __init__(self, db, max_size=20, timeout=0.5):
        self.db, self.idle, self.size, self.max_size, self.waiters = db, [], 0, max_size, deque()

    async def acquire(self):
        if self.idle:
            return self.idle.pop()
        if self.size < self.max_size:
            self.size += 1
            return await self.db.connect()
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append(fut)
        return await fut

    def release(self, conn):
        while self.waiters:
            fut = self.waiters.popleft()
            if not fut.done():
                fut.set_result(conn)
                return
        self.idle.append(conn)


def as_module(pool):
    return type(pool.__name__.upper(), (), {"Pool": pool, "PoolTimeout": PoolTimeout})


CONNECT_EACH, UNBOUNDED, BOUNDED = as_module(ConnectEach), as_module(Unbounded), as_module(Bounded)


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def kinds(world, v):
    return [i.kind for i in world.runs[v].incidents]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("module, stage", [
    (CONNECT_EACH, 0),  # New connection
    (UNBOUNDED, 1),  # Pool
    (BOUNDED, 2),  # Bounded pool
])
def test_each_stage_is_judged_from_what_the_run_did(module, stage):
    world = build_world("connection_pool", module, 5)
    results = statuses(world, module)
    assert len(results) >= 4 and {"slowdown", "spike"} <= set(kinds(world, module))
    assert world.stage_index(module) == stage
    for kind, r in zip(kinds(world, module), results):
        baseline, reuse, errors, wait, recovered = r
        assert baseline and recovered
        assert reuse == (stage >= 1)
        if kind == "slowdown":  # the incident that separates every stage
            assert errors == (stage >= 2)
            if stage == 2:
                assert not wait  # capped, but requests queue for seconds
        elif stage >= 1:  # a spike is easy once connections are reused
            assert errors and wait


def test_reference_passes_every_goal():
    world = build_world("connection_pool", "reference", 8)
    results = statuses(world, "reference")
    assert len(results) >= 6
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 3  # Bounded pool + timeout


def test_one_run_never_restarts_and_incidents_come_at_random():
    pieces = list(itertools.islice(scenario.stream("reference"), 4))
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)
    first = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 32.0, "slowdown") for i in first)
    later = list(itertools.islice(scenario.incidents(5), 30))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET and {i.kind for i in later} == {"slowdown", "spike"}
    assert all(i.cause for i in later)


def test_totals_survive_forgetting_old_minutes():
    world = build_world("connection_pool", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    asked = sum(len(p["tables"]["requests"]) for p in itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ask", 1e9) == asked


# ------------------------------------------------------------- your code


def _db() -> Database:
    return Database(random.Random(1))


@your_code(1, "a released connection is handed out again instead of opening a new one")
def test_stage1_reuses_connections():
    async def go():
        db = _db()
        pool = code.Pool(db)
        for _ in range(10):
            conn = await pool.acquire()
            await conn.query()
            pool.release(conn)
        return db.open

    assert run_virtual(go()) == 1


@your_code(2, "never more than max_size open; waiters get released connections")
def test_stage2_bounded_pool():
    async def go():
        db = _db()
        pool = code.Pool(db, max_size=5, timeout=60.0)
        peak = 0

        async def user():
            nonlocal peak
            conn = await pool.acquire()
            peak = max(peak, db.open)
            await conn.query()
            pool.release(conn)

        await asyncio.gather(*(user() for _ in range(40)))
        return peak

    assert run_virtual(go()) == 5


@your_code(2, "no refused connections during a database slowdown")
def test_stage2_no_refused_connections():
    world = build_world("connection_pool", variant(), 1)
    baseline, reuse, errors, *_ = [r.ok for r in world.runs[variant()].settled[0]]
    assert baseline and reuse and errors


@your_code(3, "acquire() gives up after timeout with PoolTimeout, and loses nothing")
def test_stage3_acquire_timeout():
    async def go():
        db = _db()
        pool = code.Pool(db, max_size=1, timeout=0.5)
        held = await pool.acquire()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        with pytest.raises(code.PoolTimeout):
            await pool.acquire()
        waited = loop.time() - t0
        pool.release(held)  # nobody is waiting any more: it must still be usable
        again = await pool.acquire()
        return waited, again is held, db.open

    waited, reused, open_ = run_virtual(go())
    assert 0.45 <= waited <= 0.6 and reused and open_ == 1


@your_code(3, "every goal passes: reuse, no refusals, p99 wait under 1 s")
def test_stage3_all_goals_pass():
    world = build_world("connection_pool", variant(), 1)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 5


def test_a_second_picture_shows_the_topology():
    from live.views import adapter_for, set_view, views_for

    world = build_world("connection_pool", "reference", 1)
    assert views_for(world) == ["lanes", "cluster", "relay"] and world.view == "lanes"  # lanes opens first
    set_view(world, "cluster")
    frame = adapter_for(world).frame("reference", 25.0)
    assert len(frame.nodes) == 2 and frame.flights and frame.state[0]


@starting_code
def test_the_relay_picture_shows_the_pool():
    from live.canvas import RED
    from live.views import adapter_for, set_view

    def relay(v: str, t: float):
        world = build_world("connection_pool", v, 1)
        set_view(world, "relay")
        frame = adapter_for(world).frame(v, t, 100)
        assert frame.users and frame.relay.label[0] and frame.state[0]
        return frame

    # A connection per request, no cap: the database refuses connections (red on the way there).
    given = relay("main", 21.0)
    assert any(colour == RED and k > 0.1 for k, colour, _ in given.hops) and given.outline == RED
    # A capped pool: at most 20 connections in use, and acquire() gives up at the pool (red, at its edge).
    solved = relay("reference", 26.0)
    assert solved.relay.fill <= 20 / 50 and solved.relay.outline == RED
    assert any(colour == RED and k < 0.1 for k, colour, _ in solved.hops)
    assert not any(colour == RED and k > 0.1 for k, colour, _ in solved.hops)
