import itertools
import random

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.db_index import scenario
from labs.db_index.storage import Heap, Row
from live.worlds import make_world

code = load("db_index", variant(), scenario.NAMES)


class HASH_ONLY:  # stage 1: a hash index for logins; ranges still scan the table
    class Table:
        def __init__(self, heap):
            self.heap, self.by_email = heap, {}

        def insert(self, row):
            self.by_email[row.email] = self.heap.insert(row)

        def find_by_email(self, email):
            pos = self.by_email.get(email)
            return None if pos is None else self.heap.get(pos)

        def signups_between(self, country, start, end):
            return self.heap.scan(country=country, start=start, end=end)


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_full_scans_read_the_whole_table_and_fail_users_as_it_grows():
    world = build_world("db_index", "main", 3)
    results = statuses(world, "main")
    assert len(results) >= 3
    assert all(r[:3] == [False, False, False] for r in results)  # whole-table reads, slow
    assert not all(r[3] for r in results)  # a later incident makes users give up
    assert world.stage_index("main") == 0  # Full scans


def test_hash_index_fixes_logins_but_ranges_still_scan():
    world = build_world("db_index", HASH_ONLY, 3)
    results = statuses(world, HASH_ONLY)
    assert len(results) >= 3
    assert all(r[:2] == [True, False] for r in results)
    assert world.stage_index(HASH_ONLY) == 1  # Hash index


def test_reference_passes_every_goal_and_pieces_join_and_totals_survive_forgetting():
    world = make_world("db_index")
    world.start("reference")
    lookups = 0
    for piece in itertools.islice(scenario.stream("reference"), 7):
        world.append("reference", piece)
        lookups += sum(1 for q in piece["tables"]["queries"] if q[2] == scenario.LOOKUP)
    results = statuses(world, "reference")
    kinds = {i.kind for i in world.runs["reference"].incidents}
    assert len(results) >= 6 and kinds == {"import", "report", "spike"}
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Hash + composite index
    run = world.runs["reference"]
    assert run.keys["queries"] == sorted(run.keys["queries"])
    assert run.keys["queries"][0] >= 60  # the first minute's raw rows are gone
    assert run.total("lookups", 1e9) == lookups


def test_the_table_only_grows():
    piece = scenario.run("reference", chunk=0)
    sizes = [n for _, n in piece["tables"]["size"]]
    assert sizes[0] >= scenario.PRELOAD and sizes == sorted(sizes)
    assert sizes[-1] - sizes[0] > 10_000  # the first import


# ------------------------------------------------------------- your code


def _table(n=3000, seed=1):
    """A table with rows inserted in random time order, like the preload and the imports."""
    rng = random.Random(seed)
    heap = Heap()
    table = code.Table(heap)
    rows = [Row(i, f"user{i}@example.com", rng.choice("ABC"), rng.uniform(0, 1000)) for i in range(n)]
    for r in rows:
        table.insert(r)
    return heap, table, rows


@your_code(1, "find_by_email reads one row, and finds the right one")
def test_stage1_lookup_reads_one_row():
    heap, table, rows = _table()
    for r in random.Random(2).sample(rows, 50):
        before = heap.reads
        assert table.find_by_email(r.email) == r
        assert heap.reads - before <= 2
    before = heap.reads
    assert table.find_by_email("nobody@example.com") is None
    assert heap.reads - before <= 1


@your_code(2, "signups_between reads only the rows it returns, even with old times inserted late")
def test_stage2_range_reads_only_what_it_returns():
    heap, table, rows = _table()
    for i in range(500):  # an import: old times, out of order
        r = Row(10_000 + i, f"late{i}@example.com", "A", random.Random(i).uniform(0, 1000))
        table.insert(r)
        rows.append(r)
    rng = random.Random(3)
    for _ in range(30):
        country = rng.choice("ABC")
        start = rng.uniform(0, 900)
        end = start + rng.uniform(0, 100)
        want = sorted(r for r in rows if r.country == country and start <= r.time < end)
        before = heap.reads
        got = sorted(table.signups_between(country, start, end))
        assert got == want
        assert heap.reads - before <= len(want) + 2


@your_code(2, "the database keeps up: every goal OK on the first incident")
def test_stage2_every_goal_passes():
    world = build_world("db_index", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert [r.ok for r in first] == [True] * 4
