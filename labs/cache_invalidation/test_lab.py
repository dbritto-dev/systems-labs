import asyncio
import itertools
import random

import pytest

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import run_virtual
from labs.cache_invalidation import reference, scenario
from labs.cache_invalidation.api import (
    Cache, CacheClient, Database, DatabaseClient, Record, Server, WriteFailed,
)

code = load("cache_invalidation", variant(), scenario.NAMES)
SEEDS = (1, 2, 3)


async def _plain_read(self, key, ttl):
    record = await self.cache.get(key)
    if record is None:
        record = await self.db.read(key)
        await self.cache.set(key, record, ttl)
    return record


class WRITE_DELETE:  # stage 1: write the database, then delete the key; plain fills
    TTL = 300.0

    class ProductCache(reference.ProductCache):
        async def read(self, key):
            return await _plain_read(self, key, WRITE_DELETE.TTL)


class DELETE_FIRST:  # delete, then write: a reader refills the old record in between
    TTL = 300.0

    class ProductCache(reference.ProductCache):
        async def read(self, key):
            return await _plain_read(self, key, DELETE_FIRST.TTL)

        async def update(self, key, record):
            await self.cache.delete(key)
            await self.db.write(key, record)


class WRITE_SET:  # write the database, then set the cache: overlapping writers set out of order
    TTL = 300.0

    class ProductCache(reference.ProductCache):
        async def read(self, key):
            return await _plain_read(self, key, WRITE_SET.TTL)

        async def update(self, key, record):
            await self.db.write(key, record)
            await self.cache.set(key, record, WRITE_SET.TTL)


class LEASE_DELETE_FIRST:  # leased fills, but the delete comes before the write: the lease is taken after it
    TTL = 30.0

    class ProductCache(reference.ProductCache):
        async def update(self, key, record):
            await self.cache.delete(key)
            await self.db.write(key, record)


class TINY_TTL:  # write, then delete, and a TTL so short that stale entries die young: the cache barely helps
    TTL = 0.2

    class ProductCache(reference.ProductCache):
        async def read(self, key):
            return await _plain_read(self, key, TINY_TTL.TTL)


def first(v, seed=1):
    world = build_world("cache_invalidation", v, 1, seed=seed)
    return world, [r.ok for r in world.runs[v].settled[0]]


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_starting_code_serves_prices_that_were_never_saved():
    world, ok = first("main")
    assert ok[0] and not ok[1] and not ok[2] and not ok[3]  # a warm cache, but unsaved and stale prices
    assert world.stage_index("main") == 0  # Cache, then database


@pytest.mark.parametrize("seed", SEEDS)
def test_write_then_delete_saves_nothing_wrong_but_slow_fills_put_old_prices_back(seed):
    world, ok = first(WRITE_DELETE, seed)
    assert ok[0] and ok[1] and not ok[2] and not ok[3] and ok[4]
    assert world.stage_index(WRITE_DELETE) == 1  # Write, then delete


@pytest.mark.parametrize("seed", SEEDS)
def test_deleting_before_the_write_lets_readers_refill_the_old_price(seed):
    world, ok = first(DELETE_FIRST, seed)
    assert ok[1] and not ok[2]
    assert world.stage_index(DELETE_FIRST) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_setting_instead_of_deleting_races_other_writers(seed):
    world, ok = first(WRITE_SET, seed)
    assert ok[1] and not (ok[2] and ok[3])
    assert world.stage_index(WRITE_SET) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_a_lease_taken_before_the_write_does_not_help(seed):
    world, ok = first(LEASE_DELETE_FIRST, seed)
    assert ok[1] and not (ok[2] and ok[3])
    assert world.stage_index(LEASE_DELETE_FIRST) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_a_tiny_ttl_is_not_a_cache(seed):
    world, ok = first(TINY_TTL, seed)
    assert not ok[0]  # the hit ratio
    assert world.stage_index(TINY_TTL) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_leased_fills_pass_the_first_campaign(seed):
    world, ok = first("reference", seed)
    assert ok == [True] * 5
    assert world.stage_index("reference") == 2  # Leased fills


def test_reference_passes_every_goal_on_every_kind_of_incident():
    world = build_world("cache_invalidation", "reference", 5, seed=5)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 5 and {i.kind for i in run.incidents} == {"campaign", "import", "slow", "restart"}
    assert all(all(r) for r in results), results


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("cache_invalidation", "reference", 7, params={"rate": 60.0})  # quieter: quicker
    run = world.runs["reference"]
    assert run.keys["reads"] == sorted(run.keys["reads"])
    assert run.keys["reads"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference", rate=60.0), 7)
    asked = sum(len(p["tables"]["reads"]) for p in pieces)
    assert run.total("asks", 1e9) == asked


def test_a_lease_is_refused_after_a_delete():
    async def main():
        cache = Cache()
        lease = await cache.lease_get(1)
        await cache.delete(1)
        late = await cache.lease_set(1, Record(1, 1, 1), lease.token, 30)
        fresh = await cache.lease_get(1)
        ok = await cache.lease_set(1, Record(2, 2, 2), fresh.token, 30)
        return late, ok, await cache.get(1)

    late, ok, found = run_virtual(main())
    assert not late and ok and found == Record(2, 2, 2)


# ------------------------------------------------------------- your code


def _pair(fail: float = 0.0):
    db = Database(10, random.Random(1))
    db.fail = fail
    cache = Cache(random.Random(2))
    servers = [Server(), Server()]
    apps = [code.ProductCache(CacheClient(cache, s), DatabaseClient(db, s)) for s in servers]
    return db, cache, servers, apps


@your_code(1, "a write the database refuses leaves the cache untouched")
def test_stage1_refused_write_never_reaches_the_cache():
    async def main():
        db, cache, _, (app, _) = _pair(fail=1.0)
        old = await app.read(3)
        with pytest.raises(WriteFailed):
            await app.update(3, Record(1, 1, 99))
        return old, await app.read(3)

    old, after = run_virtual(main())
    assert after == old


@your_code(1, "two overlapping writers: the cache ends with what the database has")
def test_stage1_overlapping_writers_leave_the_cache_right():
    async def main():
        db, cache, (paused, _), (a, b) = _pair()
        await a.read(4)  # cached
        loop = asyncio.get_running_loop()
        loop.call_later(0.0001, lambda: setattr(paused, "paused_until", loop.time() + 0.05))  # a GC pause
        async def later():
            await asyncio.sleep(0.002)
            await b.update(4, Record(6, 6, 78))

        await asyncio.gather(a.update(4, Record(5, 5, 77)), later())
        return db.rows[4], await b.read(4)

    saved, read = run_virtual(main())
    assert read == saved


@your_code(1, "no unsaved price is served in the first campaign")
def test_stage1_first_incident_serves_nothing_unsaved():
    world, ok = first(variant())
    assert ok[1]


@your_code(2, "a reader that stalls after loading an old record cannot store it after the delete")
def test_stage2_a_late_fill_is_refused():
    async def main():
        db, cache, (slow, _), (reader, writer) = _pair()
        loop = asyncio.get_running_loop()
        loop.call_later(0.006, lambda: setattr(slow, "paused_until", 0.2))  # a GC pause mid-read
        read = asyncio.ensure_future(reader.read(6))  # misses, loads the old record...
        await asyncio.sleep(0.005)
        await writer.update(6, Record(9, 9, 88))  # ...a writer commits and deletes meanwhile
        old = await read
        return old, await writer.read(6)

    old, after = run_virtual(main())
    assert old.write != 88  # the slow reader saw the old record (that is fine: it started first)
    assert after == Record(9, 9, 88)  # but it must not have put it back in the cache


@your_code(2, "a short TTL (at most 60 s) as a safety net")
def test_stage2_short_ttl():
    assert 1.0 <= code.TTL <= 60.0


@your_code(2, "the first campaign: every goal OK")
def test_stage2_first_incident_every_goal():
    world, ok = first(variant())
    assert ok == [True] * 5
    assert world.stage_index(variant()) == 2


@starting_code
def test_two_pictures_lanes_first():
    from labs.cache_invalidation.api import FILLED_STALE, REFUSED
    from live.canvas import EXTRA2, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v, at: float):
        world = build_world("cache_invalidation", v, 1)
        assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
        lanes = [adapter_for(world).frame(v, at + k / 10, 60) for k in range(50)]
        set_view(world, "cluster")
        frames = [adapter_for(world).frame(v, at + k / 20) for k in range(100)]  # in the campaign
        assert all(len(f.nodes) == scenario.APPS + 2 for f in frames)
        text = "\n".join(plain(line) for line in compose(world, v, at, 92, 30))
        assert frames[0].state[0] in text  # the line under the grid fits the smallest screen
        return world, lanes, frames

    _, given_lanes, _ = picture("main", 22.0)
    assert RED in [c for f in given_lanes for c, _ in f.outcomes]  # unsaved and stale prices at the door
    world, _, racy = picture(WRITE_DELETE, 20.0)
    fills = world.runs[WRITE_DELETE].rows("fills", 20.0, 25.0)
    assert any(f[3] == FILLED_STALE for f in fills)
    assert RED in [c for f in racy for _, _, _, c in f.flights]  # stale fills, in red
    assert RED in [f.nodes[scenario.APPS] for f in racy]  # the cache holds stale keys
    world, _, leased = picture("reference", 20.0)
    assert any(f[3] == REFUSED for f in world.runs["reference"].rows("fills", 20.0, 25.0))
    assert EXTRA2 in [c for f in leased for _, _, _, c in f.flights]  # refused fills, in orange
    assert RED not in [f.nodes[scenario.APPS] for f in leased]
