import asyncio
import itertools
import random

import pytest

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import run_virtual
from labs.hot_partition import scenario
from labs.hot_partition import reference as R
from labs.hot_partition.api import PARTITIONS, Store, home, salted

LAB = "hot_partition"
code = load(LAB, variant(), (*scenario.NAMES, "PARTITIONS", "HOT", "WINDOW", "CACHE_TTL", "COOL_FOR", "GRACE"))
# Goals: busiest < 90%, throttled ≤ 1%, p99 ≤ 100 ms, no lost increments, requests/op ≤ 1.1x after


class SALTED:  # stage 1: write-hot keys salted over six sub-keys for good; every read fans in
    class Counters(R.Counters):
        async def incr(self, key):
            if self.heat(key, "w") >= R.HOT:
                self.width[key] = self.writing[key] = R.SALTS
            await self.store.incr(self.pick(key))

        async def read(self, key):
            return sum(await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key))))


class NO_CACHE:  # adaptive salting and folding, but hot reads still go to the store
    class Counters(R.Counters):
        async def read(self, key):
            return sum(await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key))))


class SALT_EVERYTHING:  # every key salted over six sub-keys, hot or not: every read costs six requests
    class Counters(R.Counters):
        async def incr(self, key):
            await self.store.incr(salted(key, self.rng.randrange(PARTITIONS)))

        async def read(self, key):
            return sum(await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key))))

        def keys_of(self, key):
            return [salted(key, i) for i in range(PARTITIONS)]


class FORGETS_TO_FOLD:  # un-salts a cooled key without moving its sub-keys' counts back
    class Counters(R.Counters):
        async def fold(self, key):
            await asyncio.sleep(R.GRACE)
            if self.writing.get(key, 1) == 1:
                del self.width[key], self.writing[key]


class HANGS:  # a read that never returns
    class Counters(R.Counters):
        async def read(self, key):
            await asyncio.Event().wait()


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


def test_the_first_incident_is_a_viral_post_at_0_20():
    for seed in (1, 2, 99):
        first = next(scenario.incidents(seed))
        assert (first.t0, first.t1, first.kind) == (20.0, 32.0, "viral")
    incs = list(itertools.islice(scenario.incidents(3), 40))
    assert {i.kind for i in incs} == {"viral", "link", "sale", "bot"} and all(i.cause for i in incs)
    gaps = [b.t0 - a.t1 for a, b in zip(incs, incs[1:])]
    assert min(gaps) >= scenario.QUIET  # each incident is judged before the next one starts
    keys = {scenario.hot_key(i, 3) for i in incs}
    assert len(keys) == len(incs) and len({home(k) for k in keys}) == PARTITIONS  # a new key, anywhere


@starting_code
def test_hashing_by_key_melts_one_partition():
    for seed in (1, 2, 3):
        world = build_world(LAB, "main", 1, seed=seed)
        assert statuses(world, "main")[0] == [False, False, False, True, True]
        assert world.stage_index("main") == 0  # Hash by key


def test_salting_for_good_spreads_the_writes_but_reads_keep_fanning_in():
    for seed in (1, 2, 3):
        world = build_world(LAB, SALTED, 1, seed=seed)
        assert statuses(world, SALTED)[0] == [True, True, True, True, False]
        assert world.stage_index(SALTED) == 1  # Salted hot keys
    world = build_world(LAB, SALTED, 3, seed=1)
    bot = by_kind(world, SALTED)["bot"][0]
    assert bot[:3] == [False, False, False]  # salting writes does nothing for a key that is only read


def test_salting_every_key_spreads_the_fire_everywhere():
    world = build_world(LAB, SALT_EVERYTHING, 1, seed=1)
    result = statuses(world, SALT_EVERYTHING)[0]
    assert result[0] is False and result[4] is False  # six requests for every read: partitions melt
    assert world.stage_index(SALT_EVERYTHING) == 0


def test_folding_without_moving_the_counts_loses_increments():
    world = build_world(LAB, FORGETS_TO_FOLD, 1, seed=1)
    result = statuses(world, FORGETS_TO_FOLD)[0]
    assert result == [True, True, True, False, True]
    assert world.stage_index(FORGETS_TO_FOLD) == 0  # spread, but not correct


def test_without_a_cache_a_bot_still_melts_a_partition():
    world = build_world(LAB, NO_CACHE, 3, seed=1)
    assert world.stage_index(NO_CACHE) == 2  # the first incident is all writes ...
    bot = by_kind(world, NO_CACHE)["bot"][0]
    assert bot[:3] == [False, False, False]  # ... but a bot's reads all land on one partition


def test_reference_passes_every_goal_for_ten_minutes():
    kinds = set()
    for seed in (1, 3):
        world = build_world(LAB, "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 8 and all(all(r) for r in results), results
        kinds |= {i.kind for i in world.runs["reference"].incidents}
        assert world.stage_index("reference") == 2  # Adaptive salting
    assert kinds == {"viral", "link", "sale", "bot"}


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world(LAB, "reference", 7)
    run = world.runs["reference"]
    assert run.keys["ops"] == sorted(run.keys["ops"]) and run.keys["ops"][0] >= 60  # minute 0 is gone
    pieces = list(itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ops", 1e9) == sum(len(p["tables"]["ops"]) for p in pieces)
    assert all(a < b for a, b in zip(run.keys["load"], run.keys["load"][1:]))


def test_the_events_name_the_key_and_its_partition():
    world = build_world(LAB, "main", 1)
    run = world.runs["main"]
    key = scenario.hot_key(next(scenario.incidents(1)), 1)
    start = next(e for e in run.timeline if e.kind == "start")
    assert key in start.text and f"p{home(key)}" in start.text


def test_an_operation_that_never_returns_is_reported():
    with pytest.raises(RuntimeError, match="read"):
        scenario.run(HANGS, chunk=0)


# ------------------------------------------------------------- your code


def _store():
    """A store that remembers which partition every request went to."""
    seen: list[int] = []
    return Store(on_request=lambda t, p, kind, ok, hot: seen.append(p)), seen


async def _hammer(counters, key: str, writes: int, seconds: float) -> None:
    """`writes` increments of one key, evenly over `seconds`, all at once in flight."""
    tasks = []
    for _ in range(writes):
        tasks.append(asyncio.ensure_future(counters.incr(key)))
        await asyncio.sleep(seconds / writes)
    await asyncio.gather(*tasks)


@your_code(1, "heat() counts one key's operations over the last WINDOW seconds")
def test_stage1_heat():
    async def main():
        c = code.Counters(Store())
        rates = []
        for _ in range(20):
            rates.append(c.heat("post:1", "w"))
            await asyncio.sleep(0.005)
        other = c.heat("post:2", "w")
        reads = c.heat("post:1", "r")
        await asyncio.sleep(code.WINDOW + 0.05)
        return rates, other, reads, c.heat("post:1", "w")

    rates, other, reads, later = run_virtual(main())
    assert rates == sorted(rates) and rates[-1] == pytest.approx(20 / code.WINDOW)
    assert other == reads == pytest.approx(1 / code.WINDOW)  # per key, and per kind
    assert later == pytest.approx(1 / code.WINDOW)  # the old ones are forgotten


@your_code(1, "a hot key's writes spread over every partition, and none is lost")
def test_stage1_salting_spreads_writes():
    async def main():
        store, seen = _store()
        c = code.Counters(store, random.Random(1))
        await _hammer(c, "post:7", 600, 2.0)  # 300 writes/s: twice what a partition can take
        stored = sum(store.peek(k) for k in c.keys_of("post:7"))
        return seen, stored, await c.read("post:7")

    seen, stored, read = run_virtual(main())
    late = seen[len(seen) // 2:]  # once it is salted
    assert len(set(late)) >= 4
    assert max(late.count(p) for p in set(late)) < len(late) / 2
    assert stored == read == 600


@your_code(1, "the first incident (a viral post): no partition melts, nothing lost")
def test_stage1_first_incident_spreads():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0][:4] == [True, True, True, True]


@your_code(2, "salts_for: N from the heat, 2 to PARTITIONS")
def test_stage2_salts_for():
    c = code.Counters(Store())
    ns = [c.salts_for(r) for r in (40, 60, 100, 150, 300, 1000)]
    assert ns == sorted(ns) and ns[0] == 2 and ns[-1] == code.PARTITIONS
    assert ns[2] < code.PARTITIONS  # a warm key needs fewer sub-keys than a burning one


@your_code(2, "a read-hot key is served from the cache")
def test_stage2_hot_reads_come_from_the_cache():
    async def main():
        store, seen = _store()
        c = code.Counters(store)
        await store.incr("item:9", 5)
        seen.clear()
        values = []
        for _ in range(400):  # 400 reads in a second
            values.append(await c.read("item:9"))
            await asyncio.sleep(1 / 400 - 0.0)
        return values, len(seen)

    values, requests = run_virtual(main())
    assert set(values) == {5}
    assert requests <= 40  # instead of 400


@your_code(2, "a cooled key is folded back into one key, with every increment")
def test_stage2_fold_back():
    async def main():
        store, _ = _store()
        c = code.Counters(store, random.Random(2))
        await _hammer(c, "post:3", 400, 1.0)  # hot: salted
        wide = list(c.keys_of("post:3"))
        for _ in range(int((code.COOL_FOR + code.GRACE + 2) * 10)):  # then 10 writes/s: cool
            await c.incr("post:3")
            await asyncio.sleep(0.1)
        await asyncio.sleep(2.0)
        return wide, list(c.keys_of("post:3")), dict(store.values)

    wide, narrow, values = run_virtual(main())
    total = 400 + int((code.COOL_FOR + code.GRACE + 2) * 10)
    assert len(wide) > 1 and narrow == ["post:3"]
    assert values.get("post:3") == total  # every sub-key's count moved back
    assert all(v == 0 for k, v in values.items() if k != "post:3")


@your_code(2, "every goal OK on the first incident")
def test_stage2_first_incident_every_goal():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0] == [True] * 5
    assert world.stage_index(variant()) == 2


# ------------------------------------------------------------- the pictures


@starting_code
def test_two_pictures_the_cluster_first():
    from live.canvas import EXTRA2, PURPLE, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    worlds = {v: build_world(LAB, v, 1) for v in ("main", "reference")}
    assert views_for(worlds["main"]) == ["fanout", "cluster", "lanes"] and worlds["main"].view == "fanout"  # opens with fanout
    set_view(worlds["main"], "cluster")  # the checks below are about the cluster picture

    def pictures(v: str, t: float):
        world = worlds[v]
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == PARTITIONS
        assert frame.state[0] in "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        assert lanes.state[0] in "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert len(lanes.state[0]) <= 13
        return frame, lanes

    hot = home(scenario.hot_key(next(scenario.incidents(1)), 1))
    for t in (24.0, 28.0):
        frame, lanes = pictures("main", t)  # one partition melts: red, throttled requests die
        assert frame.nodes[hot] == RED and frame.drops
        assert [p for p, c in enumerate(frame.nodes) if c == RED] == [hot]
        assert any(c == RED for c, _ in lanes.outcomes) and lanes.fill > 0.9
        frame, lanes = pictures("reference", t)  # the hot key spread over every partition
        assert RED not in frame.nodes and not frame.drops
        assert len({dest for _, dest, _, c in frame.flights if c == PURPLE}) >= 3
    frame, _ = pictures("main", 45.0)
    assert RED not in frame.nodes
    assert all(c != EXTRA2 for _, _, _, c in pictures("reference", 45.0)[0].flights)  # no fan-in once cool


@starting_code
def test_the_fanout_picture_shows_each_partition():
    from live.canvas import EXTRA2, PURPLE, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view

    hot = home(scenario.hot_key(next(scenario.incidents(1)), 1))

    def fan(v: str, t: float):
        world = build_world(LAB, v, 1)
        set_view(world, "fanout")
        frame = adapter_for(world).frame(v, t, 100)
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        shown = [leaf.label[0] in text or (leaf.short and leaf.short in text) for leaf in frame.leaves]
        assert all(shown) and frame.state[0] in text  # each name, or its short form on this small screen
        return frame

    given, solved = fan("main", 24.0), fan("reference", 24.0)
    assert len(given.leaves) == PARTITIONS and given.leaves[hot].label[0].startswith(f"p{hot} ")  # "p1 99%": its
    # colour says it is hot (red melting, else purple), the words its load
    # Hash by key: the hot partition melts (red), the hot key's requests all go there and some are throttled.
    assert [p for p, leaf in enumerate(given.leaves) if leaf.outline == RED] == [hot]
    assert {j for j, _, c, _ in given.hops if c == PURPLE} == {hot} and any(c == RED for _, _, c, _ in given.hops)
    assert given.relay.fill == 0  # one request per operation: no fan-in
    # Salted: the hot key's writes spread over the partitions, none melts, and Counters fans reads in.
    assert not any(leaf.outline == RED for leaf in solved.leaves)
    assert len({j for j, _, c, _ in solved.hops if c == PURPLE}) >= 3
    assert solved.relay.fill > 0 and solved.relay.outline == EXTRA2
