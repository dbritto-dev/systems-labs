import asyncio
import itertools
import random

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.optimistic_locking import reference, scenario
from labs.optimistic_locking.api import START_STOCK, Conflict, Database, current_request

code = load("optimistic_locking", variant(), scenario.NAMES)
SEEDS = (1, 2, 3)


class CHECK:  # stage 1: a version check, and a 409 on every conflict
    MAX_TRIES = 1
    backoff = staticmethod(reference.backoff)

    class StockService(reference.StockService):
        async def adjust(self, item, delta):
            row = await self.db.read(item)
            if not await self.db.compare_and_set(item, row.value + delta, row.version):
                raise Conflict(item)
            return row.value + delta


class NO_REREAD:  # retries, but with the value and version it read first: it can never win again
    MAX_TRIES = 8
    backoff = staticmethod(reference.backoff)

    class StockService(reference.StockService):
        async def adjust(self, item, delta):
            row = await self.db.read(item)
            for attempt in range(8):
                if attempt:
                    await asyncio.sleep(reference.backoff(attempt, self.rng))
                if await self.db.compare_and_set(item, row.value + delta, row.version):
                    return row.value + delta
            raise Conflict(item)


class NO_CAP:  # re-reads and retries, but the waits double without a cap: users wait too long
    MAX_TRIES = 8

    @staticmethod
    def backoff(attempt, rng):
        return 0.1 * 2 ** attempt

    class StockService(reference.StockService):
        async def adjust(self, item, delta):
            for attempt in range(8):
                if attempt:
                    await asyncio.sleep(NO_CAP.backoff(attempt, self.rng))
                row = await self.db.read(item)
                if await self.db.compare_and_set(item, row.value + delta, row.version):
                    return row.value + delta
            raise Conflict(item)


class NO_BACKOFF:  # re-reads and retries at once: the buyers of one drop collide again, round after round
    MAX_TRIES = 8

    @staticmethod
    def backoff(attempt, rng):
        return 0.0

    class StockService(reference.StockService):
        async def adjust(self, item, delta):
            for attempt in range(8):
                row = await self.db.read(item)
                if await self.db.compare_and_set(item, row.value + delta, row.version):
                    return row.value + delta
            raise Conflict(item)


class LOCAL_LOCK:  # an asyncio.Lock per item, last write wins: each app server has its own locks
    MAX_TRIES = 1
    backoff = staticmethod(reference.backoff)

    class StockService(reference.StockService):
        def __init__(self, db, rng=None):
            super().__init__(db, rng)
            self.locks = {}

        async def adjust(self, item, delta):
            async with self.locks.setdefault(item, asyncio.Lock()):
                row = await self.db.read(item)
                await self.db.write(item, row.value + delta)
                return row.value + delta


def first(v, seed=1):
    world = build_world("optimistic_locking", v, 1, seed=seed)
    return world, [r.ok for r in world.runs[v].settled[0]]


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_starting_code_loses_updates_in_the_flash_sale():
    world, ok = first("main")
    assert ok == [True, False, True, True, True]  # fast and always served, but updates are lost
    assert world.stage_index("main") == 0  # Last write wins


@pytest.mark.parametrize("seed", SEEDS)
def test_a_version_check_loses_nothing_but_answers_409s(seed):
    world, ok = first(CHECK, seed)
    assert ok[1] and not ok[2] and not ok[4]  # nothing lost; too many 409s, too few served
    assert world.stage_index(CHECK) == 1  # Version check


@pytest.mark.parametrize("seed", SEEDS)
def test_a_lock_inside_one_app_server_still_loses_updates(seed):
    world, ok = first(LOCAL_LOCK, seed)
    assert not ok[1]
    assert world.stage_index(LOCAL_LOCK) == 0


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_retrying_the_stale_version_never_wins(seed):
    world, ok = first(NO_REREAD, seed)
    assert ok[1] and not ok[2]
    assert world.stage_index(NO_REREAD) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_an_uncapped_backoff_serves_everyone_too_late(seed):
    world, ok = first(NO_CAP, seed)
    assert ok[1] and ok[2] and not ok[3]  # nothing lost, few 409s, but the p99 is far too long
    assert world.stage_index(NO_CAP) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_retrying_at_once_keeps_colliding(seed):
    world, ok = first(NO_BACKOFF, seed)
    assert ok[1] and not ok[2] and not ok[4]  # nothing lost, but a quarter of the buyers still get a 409
    assert world.stage_index(NO_BACKOFF) == 1


def test_reference_passes_every_goal_on_every_kind_of_incident():
    world = build_world("optimistic_locking", "reference", 5, seed=5)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 4 and {i.kind for i in run.incidents} == {"flash", "import", "slow"}
    assert all(all(r) for r in results), results
    assert world.stage_index("reference") == 2  # Retry and merge


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("optimistic_locking", "reference", 7, params={"rate": 15.0})  # quieter: quicker
    run = world.runs["reference"]
    assert run.keys["requests"] == sorted(run.keys["requests"])
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference", rate=15.0), 7)
    asked = sum(len(p["tables"]["requests"]) for p in pieces)
    assert run.total("asks", 1e9) == asked


def test_the_database_counts_what_a_blind_write_erases():
    async def main():
        db = Database()
        current_request.set((1, -1))
        await db.read(7)
        current_request.set((2, -2))
        await db.read(7)
        await db.write(7, START_STOCK - 2)
        current_request.set((1, -1))
        await db.write(7, START_STOCK - 1)  # computed from the old read: erases request 2's update
        return db

    db = run_virtual(main())
    assert db.value(7) == START_STOCK - 1  # 3 units sold, the stock says 1


# ------------------------------------------------------------- your code


def _db():
    db = Database(latency=0.01)
    db.log = []
    db.on_write = lambda who, started, result, lost: db.log.append(lost)
    return db


async def _adjust(service, item, delta, rid):
    current_request.set((rid, delta))
    try:
        return await service.adjust(item, delta)
    except Conflict:
        return "conflict"


@your_code(1, "two app servers changing one row at once: no update is lost")
def test_stage1_concurrent_writes_lose_nothing():
    async def main():
        db = _db()
        a, b = code.StockService(db, random.Random(1)), code.StockService(db, random.Random(2))
        answers = await asyncio.gather(_adjust(a, 5, -2, 1), _adjust(b, 5, -3, 2))
        return answers, db.value(5), db.log

    answers, value, lost = run_virtual(main())
    applied = sum(d for d, ans in zip((-2, -3), answers) if ans != "conflict")
    assert value == START_STOCK + applied and sum(lost) == 0
    assert "conflict" in answers or applied == -5


@your_code(1, "nothing is lost in the first flash sale")
def test_stage1_first_incident_loses_nothing():
    world, ok = first(variant())
    assert ok[1]


@your_code(2, "backoff: random between 0 and min(CAP, BASE * 2 ** attempt), never above CAP")
def test_stage2_backoff_is_jittered_and_capped():
    rng = random.Random(3)
    for attempt in (1, 2, 3, 10, 100, 5000):
        waits = [code.backoff(attempt, rng) for _ in range(200)]
        ceiling = min(0.1, 0.005 * 2 ** min(attempt, 30))  # CAP and BASE as given
        assert all(0 <= w <= ceiling + 1e-12 for w in waits)
        assert len(set(waits)) > 100  # jittered, not one fixed wait
    assert code.backoff(2, random.Random(9)) == code.backoff(2, random.Random(9))  # it uses rng


@your_code(2, "twenty buyers of one row at once: every one succeeds, the stock is exact")
def test_stage2_retries_merge_every_change():
    async def main():
        db = _db()
        apps = [code.StockService(db, random.Random(k)) for k in range(3)]
        answers = await asyncio.gather(*(_adjust(apps[k % 3], 9, -1, k) for k in range(20)))
        return answers, db.value(9), db.log

    answers, value, lost = run_virtual(main())
    assert "conflict" not in answers
    assert value == START_STOCK - 20 and sum(lost) == 0


@your_code(2, "the first flash sale: every goal OK")
def test_stage2_first_incident_every_goal():
    world, ok = first(variant())
    assert ok == [True] * 5
    assert world.stage_index(variant()) == 2


def test_two_pictures_lanes_first():
    from live.canvas import EXTRA2, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v: str):
        world = build_world("optimistic_locking", v, 1)
        assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
        lanes = adapter_for(world).frame(v, 25.0, 60)
        set_view(world, "cluster")
        frames = [adapter_for(world).frame(v, 25.0 + k / 10) for k in range(10)]  # in the flash sale
        assert all(len(f.nodes) == scenario.APPS + 1 for f in frames)
        text = "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
        assert frames[0].state[0] in text  # the line under the grid fits the smallest screen
        return lanes, frames

    (given_lanes, given), (check_lanes, check) = picture("main"), picture(CHECK)
    flights = [c for f in given for _, _, _, c in f.flights]
    assert RED in flights and RED in [f.nodes[-1] for f in given]  # writes that erase others, in red
    assert RED in [c for c, _ in given_lanes.outcomes]
    flights = [c for f in check for _, _, _, c in f.flights]
    assert RED not in flights and EXTRA2 in flights  # conflicts instead, in orange
    assert EXTRA2 in [c for c, _ in check_lanes.outcomes]  # 409s at the door
