import asyncio
import itertools

import pytest

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import now, run_virtual
from labs.zero_downtime_migration import reference as ref
from labs.zero_downtime_migration import scenario
from live.canvas import RED

code = load("zero_downtime_migration", variant(), scenario.NAMES)


class _Variant:  # the reference's names, for the stage variants below to override
    read_name, write_name = staticmethod(ref.read_name), staticmethod(ref.write_name)
    busy, backfill, verify = staticmethod(ref.busy), staticmethod(ref.backfill), staticmethod(ref.verify)
    BATCH, PAUSE, LOAD_MAX, LAG_MAX, GRACE = ref.BATCH, ref.PAUSE, ref.LOAD_MAX, ref.LAG_MAX, ref.GRACE


async def _one_copy(db, m, fleet):
    """Stage 1: expand/contract, the new column filled by one copy of every row; no verify."""
    await db.add_column(m.new)
    await fleet.all_new()
    await db.copy(m.old, m.new)
    await fleet.released()
    m.read_new = True
    m.write_old = False
    await asyncio.sleep(ref.GRACE)
    await db.drop_column(m.old)


class ONE_COPY(_Variant):  # stands in for a main.py module at stage 1
    migrate = staticmethod(_one_copy)


async def _batches_no_verify(db, m, fleet):
    """Stage 2 without verify(): batches and throttling, but what a rollback wrote stays stale."""
    await db.add_column(m.new)
    await fleet.all_new()
    await ref.backfill(db, m)
    await fleet.released()
    m.read_new = True
    m.write_old = False
    await asyncio.sleep(ref.GRACE)
    await db.drop_column(m.old)


class NO_VERIFY(_Variant):
    migrate = staticmethod(_batches_no_verify)


def _never_busy(db) -> bool:
    return False


async def _reference_migrate(db, m, fleet):
    """The reference's migrate, calling this module's busy (so a variant can swap it)."""
    await db.add_column(m.new)
    await fleet.all_new()
    for first in range(0, db.rows, ref.BATCH):
        await db.copy(m.old, m.new, first, first + ref.BATCH)
        await asyncio.sleep(ref.PAUSE)
    await fleet.released()
    for first in range(0, db.rows, ref.BATCH):
        if await db.diff(m.old, m.new, first, first + ref.BATCH):
            await db.copy(m.old, m.new, first, first + ref.BATCH)
            await asyncio.sleep(ref.PAUSE)
    m.read_new = True
    m.write_old = False
    await asyncio.sleep(ref.GRACE)
    await db.drop_column(m.old)


class NO_THROTTLE(_Variant):  # batches and a pause, but never waits for a busy database
    busy = staticmethod(_never_busy)
    migrate = staticmethod(_reference_migrate)


SEEDS = (1, 2, 3, 4)
# Goals: errors, p99, wrong, done


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", SEEDS)
@starting_code
def test_renaming_in_place_fails_every_old_instance(seed):
    world = build_world("zero_downtime_migration", "main", 2, seed=seed)
    assert statuses(world, "main")[0] == [False, True, True, True]
    assert world.stage_index("main") == 0  # Rename in place


@pytest.mark.parametrize("seed", SEEDS)
def test_one_big_copy_blocks_writes_and_misses_the_rollback(seed):
    world = build_world("zero_downtime_migration", ONE_COPY, 2, seed=seed)
    assert statuses(world, ONE_COPY)[0] == [True, False, False, True]
    assert world.stage_index(ONE_COPY) == 1  # Expand/contract


@pytest.mark.parametrize("seed", SEEDS)
def test_batches_without_verify_leave_what_the_rollback_wrote(seed):
    world = build_world("zero_downtime_migration", NO_VERIFY, 2, seed=seed)
    assert statuses(world, NO_VERIFY)[0] == [True, True, False, True]
    assert world.stage_index(NO_VERIFY) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_batches_that_ignore_a_busy_database_break_write_p99(seed):
    world = build_world("zero_downtime_migration", NO_THROTTLE, 2, seed=seed)
    assert statuses(world, NO_THROTTLE)[0] == [True, False, True, True]  # cold instances after the rollback
    assert world.stage_index(NO_THROTTLE) == 1


def test_a_backfill_that_ignores_a_busy_database_alerts_on_every_lag_and_peak():
    world = build_world("zero_downtime_migration", NO_THROTTLE, 8, seed=5)
    run = world.runs[NO_THROTTLE]
    judged = [i for i in run.incidents if None not in run.settled.get(i.index, [None])]
    busy = [i.index for i in judged if i.kind in ("lag", "peak")]
    assert busy and all(not run.settled[i][1].ok for i in busy)  # p99 alerts on every lag and peak


@pytest.mark.parametrize("seed", (1, 3, 5))
def test_reference_passes_every_goal_for_ten_minutes(seed):
    world = build_world("zero_downtime_migration", "reference", 10, seed=seed)
    results = statuses(world, "reference")
    assert len(results) >= 3 and all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Throttled, verified backfill


def test_pieces_join_and_the_first_incident_is_fixed():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 80.0, "rollback") for i in first)
    a = list(itertools.islice(scenario.incidents(4), 30))
    gaps = [n.t0 - p.t1 for p, n in zip(a, a[1:])]
    assert min(gaps) >= scenario.QUIET and {i.kind for i in a} == {"deploy", "rollback", "lag", "peak"}
    assert len({i.cause for i in a}) >= 6
    pieces = list(itertools.islice(scenario.stream("reference"), 2))
    starts = [r[1] for p in pieces for r in p["tables"]["requests"]]
    assert starts == sorted(starts) and starts[-1] < 120
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)
    assert scenario.rename(0) == ("fullname", "display_name") and scenario.rename(10) == ("fullname2", "display_name2")


@starting_code
def test_both_pictures_show_the_migration():
    from live.views import adapter_for, set_view, views_for

    world = build_world("zero_downtime_migration", "main", 1)
    assert views_for(world) == ["relay", "cluster", "lanes"] and world.view == "relay"  # opens with relay
    set_view(world, "lanes")  # the checks below are about the lanes picture
    lane = adapter_for(world).frame("main", 21.0, 100)
    assert lane.closed and any(colour == RED for colour, _ in lane.outcomes)  # old instances fail
    set_view(world, "cluster")
    frame = adapter_for(world).frame("main", 21.0)
    assert len(frame.nodes) == scenario.INSTANCES + 3 and frame.flights and frame.drops
    assert RED in frame.nodes[:scenario.INSTANCES]


@starting_code
def test_the_relay_picture_shows_the_fleet_and_the_backfill():
    from live.canvas import EXTRA2, PURPLE, RED
    from live.views import adapter_for, set_view

    def relay(v):
        world = build_world("zero_downtime_migration", v, 1)
        set_view(world, "relay")
        return [adapter_for(world).frame(v, 20.0 + k / 4, 100) for k in range(160)]  # the first window

    given, solved = relay("main"), relay("reference")
    assert all(f.relay.label[0] and f.state[0] for f in given + solved)
    assert given[0].relay.fill == 0 and solved[-1].relay.fill == 1  # the share of the fleet on the new release
    # The given migration renames the column under the old release: requests fail on the way to the
    # database (red) and the fleet is outlined red. The reference mixes old and new instances safely
    # (orange) while its backfill copies fly purple.
    assert RED in [c for f in given for _, c, _ in f.hops] and RED in [f.relay.outline for f in given]
    assert RED not in [c for f in solved for _, c, _ in f.hops] and RED not in [f.relay.outline for f in solved]
    assert PURPLE in [c for f in solved for _, c, _ in f.hops] and EXTRA2 in [f.relay.outline for f in solved]


# ------------------------------------------------------------- your code


class M:
    """A migration's names and flags, like the one every instance shares."""

    def __init__(self) -> None:
        self.table, self.old, self.new = "users", "fullname", "display_name"
        self.read_new, self.write_old = False, True


class FakeDb:
    """A table of `rows` rows that records every statement."""

    def __init__(self, rows: int = 1000, load: float = 0.3, lag: float = 0.0, differ=()) -> None:
        self.rows, self._load, self._lag = rows, load, lag
        self.differ = set(differ)  # ids whose two columns differ
        self.log: list[tuple] = []

    def load(self) -> float:
        return self._load

    def lag(self) -> float:
        return self._lag

    async def select(self, uid, col):
        self.log.append(("select", uid, col))
        return f"name-{uid}"

    async def update(self, uid, values):
        self.log.append(("update", uid, dict(values)))

    async def add_column(self, col):
        self.log.append(("add", col))

    async def drop_column(self, col):
        self.log.append(("drop", col))

    async def rename_column(self, old, new):
        self.log.append(("rename", old, new))

    async def copy(self, src, dst, first=0, last=None):
        last = self.rows if last is None else min(last, self.rows)
        self.log.append(("copy", src, dst, first, last, now()))
        self.differ -= set(range(first, last))
        await asyncio.sleep(0.001)
        return last - first

    async def diff(self, a, b, first=0, last=None):
        last = self.rows if last is None else min(last, self.rows)
        self.log.append(("diff", a, b, first, last))
        return sum(1 for i in self.differ if first <= i < last)


class FakeFleet:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    async def all_new(self):
        await asyncio.sleep(1.0)
        self.db.log.append(("all_new",))

    async def released(self):
        await asyncio.sleep(1.0)
        self.db.log.append(("released",))


def _run(coro):
    return run_virtual(coro)


@your_code(1, "write_name writes both columns in one update while m.write_old, then only the new one")
def test_stage1_write_name_dual_writes():
    db, m = FakeDb(), M()
    _run(code.write_name(db, m, 7, "Ada"))
    assert db.log == [("update", 7, {"display_name": "Ada", "fullname": "Ada"})]
    m.write_old = False
    db.log.clear()
    _run(code.write_name(db, m, 7, "Ada L."))
    assert db.log == [("update", 7, {"display_name": "Ada L."})]


@your_code(1, "read_name reads the old column until m.read_new, then the new one")
def test_stage1_read_name_follows_the_flag():
    db, m = FakeDb(), M()
    assert _run(code.read_name(db, m, 3)) == "name-3" and db.log[-1] == ("select", 3, "fullname")
    m.read_new = True
    _run(code.read_name(db, m, 3))
    assert db.log[-1] == ("select", 3, "display_name")


@your_code(1, "migrate: add, wait for all new, fill, wait for the final release, switch, drop last")
def test_stage1_migrate_expands_then_contracts():
    db, m = FakeDb(rows=300), M()
    _run(code.migrate(db, m, FakeFleet(db)))
    kinds = [e[0] for e in db.log]
    assert "rename" not in kinds and kinds[0] == "add" and kinds[-1] == "drop"
    assert db.log[-1] == ("drop", "fullname")
    assert kinds.index("all_new") < kinds.index("copy") < kinds.index("released") < len(kinds) - 1
    assert m.read_new and not m.write_old
    copied = set()
    for e in db.log:
        if e[0] == "copy":
            assert e[1:3] == ("fullname", "display_name")
            copied |= set(range(e[3], e[4]))
    assert copied == set(range(300))


@your_code(1, "nothing fails: old instances keep their column through the rollback")
def test_stage1_no_errors():
    world = build_world("zero_downtime_migration", variant(), 2)
    assert world.runs[variant()].settled[0][0].ok


@your_code(2, "busy: load above LOAD_MAX, or replica lag above LAG_MAX")
def test_stage2_busy():
    assert not code.busy(FakeDb(load=code.LOAD_MAX - 0.05, lag=code.LAG_MAX / 2))
    assert code.busy(FakeDb(load=code.LOAD_MAX + 0.05))
    assert code.busy(FakeDb(lag=code.LAG_MAX + 0.1))


@your_code(2, "backfill copies every row once, BATCH rows at a time, with a pause between batches")
def test_stage2_backfill_in_batches():
    db, m = FakeDb(rows=1050), M()
    assert _run(code.backfill(db, m)) == 1050
    copies = [e for e in db.log if e[0] == "copy"]
    assert all(e[4] - e[3] <= code.BATCH for e in copies)
    assert sorted(i for e in copies for i in range(e[3], e[4])) == list(range(1050))
    times = [e[5] for e in copies]
    assert all(b - a >= code.PAUSE - 1e-9 for a, b in zip(times, times[1:]))


@your_code(2, "backfill waits while the database is busy")
def test_stage2_backfill_waits_while_busy():
    db, m = FakeDb(rows=200, load=0.9), M()

    async def calm_later():
        task = asyncio.ensure_future(code.backfill(db, m))
        await asyncio.sleep(3.0)
        assert not [e for e in db.log if e[0] == "copy"]  # nothing copied while busy
        db._load = 0.3
        return await task

    assert _run(calm_later()) == 200


@your_code(2, "verify re-copies only the batches whose columns differ")
def test_stage2_verify_recopies_what_differs():
    db, m = FakeDb(rows=1000, differ={5, 512, 513}), M()
    fixed = _run(code.verify(db, m))
    copies = [e for e in db.log if e[0] == "copy"]
    assert copies and not db.differ  # every stale row copied again
    assert sum(e[4] - e[3] for e in copies) <= 2 * code.BATCH and fixed == sum(e[4] - e[3] for e in copies)
    diffs = [e for e in db.log if e[0] == "diff"]
    assert sorted(i for e in diffs for i in range(e[3], e[4])) == list(range(1000))


@your_code(2, "no errors, write p99 under 40 ms, no wrong names, done in time")
def test_stage2_every_goal():
    world = build_world("zero_downtime_migration", variant(), 2)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 4
    assert world.stage_index(variant()) == 2
