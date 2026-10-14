import asyncio
import itertools

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.n_plus_one_queries import scenario

code = load("n_plus_one_queries", variant(), scenario.NAMES)


class BATCH:  # stage 1 as people write it: one IN query for the customers
    @staticmethod
    async def load_page(page_id, db):
        orders = await db.fetch_orders(page_id)
        customers = await db.fetch_customers(o["customer_id"] for o in orders)
        return [{"order": o, "customer": customers[o["customer_id"]]} for o in orders]


class GATHER:  # the tempting non-fix: the same N+1 queries, all at once
    @staticmethod
    async def load_page(page_id, db):
        orders = await db.fetch_orders(page_id)
        found = await asyncio.gather(*(db.fetch_customer(o["customer_id"]) for o in orders))
        return [{"order": o, "customer": c} for o, c in zip(orders, found)]


def results(world, v):
    run = world.runs[v]
    return [(inc.kind, [r.ok for r in run.settled[inc.index]]) for inc in run.incidents
            if all(r is not None for r in run.settled.get(inc.index, [None]))]


# ------------------------------------------------------------- given behaviour


def test_the_starting_code_is_n_plus_one_and_correct():
    world = build_world("n_plus_one_queries", "main", 1)
    first = [r.ok for r in world.runs["main"].settled[0]]
    assert first[0] and not first[1]  # right pages, too many queries
    assert world.stage_index("main") == 0


def test_running_the_queries_concurrently_is_still_n_plus_one():
    world = build_world("n_plus_one_queries", GATHER, 2)
    assert world.stage_index(GATHER) == 0
    assert all(not ok[1] for _, ok in results(world, GATHER))


def test_batching_is_two_round_trips_too_slow_only_when_the_database_is():
    world = build_world("n_plus_one_queries", BATCH, 4)
    res = results(world, BATCH)
    assert len(res) >= 4 and world.stage_index(BATCH) == 1
    for kind, ok in res:
        assert ok == ([True, True, True, False, True] if kind == "slow_db" else [True] * 5), (kind, ok)


def test_reference_passes_every_goal_on_every_incident():
    kinds = set()
    for seed in (1, 2):
        world = build_world("n_plus_one_queries", "reference", 6, seed=seed)
        res = results(world, "reference")
        assert len(res) >= 2 and all(all(ok) for _, ok in res), res
        assert world.stage_index("reference") == 2
        kinds |= {kind for kind, _ in res}
    assert kinds == {"slow_db", "big_pages", "spike"}


def test_incidents_are_random_but_the_first_is_a_slow_database():
    firsts = [next(scenario.incidents(s)) for s in (1, 5, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "slow_db") for i in firsts)
    later = list(itertools.islice(scenario.incidents(3), 40))
    assert {i.kind for i in later} == {"slow_db", "big_pages", "spike"} and all(i.cause for i in later)


def test_pieces_join_and_totals_survive_forgetting():
    world = build_world("n_plus_one_queries", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["pages"] == sorted(run.keys["pages"]) and run.keys["pages"][0] >= 60
    pieces = itertools.islice(scenario.stream("reference"), 7)
    assert run.total("pages", 1e9) == sum(len(p["tables"]["pages"]) for p in pieces)


# ------------------------------------------------------------- your code


def first(v=None):
    v = v or variant()
    return [r.ok for r in build_world("n_plus_one_queries", v, 1).runs[v].settled[0]]


@your_code(1, "two queries per page: the orders, then all their customers at once")
def test_stage1_batched():
    assert first()[:3] == [True, True, True]


@your_code(2, "one query per page, so a slow database costs one round trip")
def test_stage2_joined():
    assert first() == [True] * 5


def test_a_second_picture_shows_every_query():
    from live.canvas import plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def queries(v: str) -> int:
        world = build_world("n_plus_one_queries", v, 1)
        assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, 10.0)
        assert len(frame.nodes) == 2 and any(src == -1 for src, _, _, _ in frame.flights)
        text = "\n".join(plain(line) for line in compose(world, v, 10.0, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        return sum(1 for src, dest, _, _ in frame.flights if (src, dest) == (0, 1))

    assert queries("main") >= 4 * queries("reference")  # N+1 is a swarm of round trips, a join one each
