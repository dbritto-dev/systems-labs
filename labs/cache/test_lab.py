import asyncio
import itertools
import random

from core.contract import load
from core.services import SlowDatabase
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.cache import scenario

code = load("cache", variant(), scenario.NAMES)


def _cache_aside():
    """Stage 1 as most people first write it: no single-flight, fixed TTL."""
    from core.vtime import now
    from labs.cache.reference import Cache as Base

    class Cache(Base):
        def store(self, key, value):
            self.data[key] = (value, now() + self.ttl)

    async def get(key, *, cache, db):
        v = cache.lookup(key)
        if v is None:
            v = await db.read(key)
            cache.store(key, v)
        return v

    class CacheAside:  # stands in for a main.py module
        pass

    CacheAside.Cache, CacheAside.get = Cache, staticmethod(get)
    return CacheAside


CACHE_ASIDE = _cache_aside()


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_no_cache_fails_the_p99_goal():
    world = build_world("cache", "main", 1)
    first = world.runs["main"].settled[0]
    assert [r.ok for r in first] == [False, False, False]
    assert world.stage_index("main") == 0  # No cache


def test_cache_aside_fails_the_database_goal_on_every_flush():
    world = build_world("cache", CACHE_ASIDE, 4)
    results = statuses(world, CACHE_ASIDE)
    assert len(results) >= 3
    assert all(r[0] and not r[1] for r in results)  # good hit ratio, duplicate loads
    assert world.stage_index(CACHE_ASIDE) == 1


def test_reference_passes_every_goal():
    world = build_world("cache", "reference", 5)
    results = statuses(world, "reference")
    assert len(results) >= 4
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Stampede-safe


def test_flushes_come_at_random_but_the_first_is_at_twenty_seconds():
    first = [next(scenario.incidents(seed)) for seed in (1, 7)]
    assert all(i.t0 == 20.0 and i.cause for i in first)
    times = [i.t0 for i in itertools.islice(scenario.incidents(3), 40)]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert min(gaps) >= scenario.QUIET and max(gaps) > 2 * min(gaps)


# ------------------------------------------------------------- your code


def _run(coro_factory):
    async def main():
        return await coro_factory()
    return run_virtual(main())


@your_code(1, "Cache.lookup / Cache.store honour the TTL")
def test_stage1_lookup_and_ttl():
    async def go():
        cache = code.Cache(ttl=10.0, rng=random.Random(1))
        assert cache.lookup("k") is None
        cache.store("k", "v")
        assert cache.lookup("k") == "v"
        await asyncio.sleep(13)  # past any TTL jitter of up to +20%
        return cache.lookup("k")

    assert _run(go) is None


@your_code(1, "get() serves repeat reads from memory")
def test_stage1_get_is_cache_aside():
    async def go():
        db = SlowDatabase()
        cache = code.Cache(ttl=30.0, rng=random.Random(1))
        for _ in range(5):
            assert await code.get("k", cache=cache, db=db) == "value-k"
        return db.reads

    assert _run(go) == 1


@your_code(2, "single-flight: 100 concurrent misses for one key cause 1 database read")
def test_stage2_single_flight():
    async def go():
        db = SlowDatabase()
        cache = code.Cache(ttl=30.0, rng=random.Random(1))
        values = await asyncio.gather(*(code.get("hot", cache=cache, db=db) for _ in range(100)))
        assert set(values) == {"value-hot"}
        return db.reads

    assert _run(go) == 1


@your_code(2, "jittered TTLs: keys stored together expire at different times")
def test_stage2_jittered_ttl():
    async def go():
        cache = code.Cache(ttl=30.0, rng=random.Random(1))
        for k in range(50):
            cache.store(k, k)
        await asyncio.sleep(20.0)
        alive = []
        for _ in range(20):
            await asyncio.sleep(1.0)
            alive.append(sum(cache.lookup(k) is not None for k in range(50)))
        return alive

    alive = _run(go)  # sampled from 21 s to 40 s: expiries spread over several seconds
    assert len({a for a in alive if 0 < a < 50}) >= 3


def test_a_second_picture_shows_the_topology():
    from live.views import adapter_for, set_view, views_for

    world = build_world("cache", "reference", 1)
    assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"
    set_view(world, "cluster")
    frame = adapter_for(world).frame("reference", 25.0)  # in the first incident
    assert len(frame.nodes) >= 2 and frame.flights and frame.state[0]
    assert any(src == -1 for src, _, _, _ in frame.flights)  # requests come from the clients
