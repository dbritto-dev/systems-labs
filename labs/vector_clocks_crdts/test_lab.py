import functools
import itertools

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from labs.vector_clocks_crdts import reference as ref
from labs.vector_clocks_crdts import scenario

code = load("vector_clocks_crdts", variant(), (*scenario.NAMES, "compare", "keep_newest", "ORSet"))


# ------------------------------------------------------------- one replica per stage, as people write them


class VectorClocks(ref.CartNode):  # stage 1: siblings with vector clocks, merged (a union) on read
    def items(self, cart):
        return set().union(*(items for _, items in self.carts.get(cart, [])))

    def add(self, cart, item):
        self.put(cart, self.items(cart) | {item})

    def remove(self, cart, item):
        self.put(cart, self.items(cart) - {item})

    def put(self, cart, items):
        clock = {}
        for seen, _ in self.carts.get(cart, []):
            for node, n in seen.items():
                clock[node] = max(clock.get(node, 0), n)
        clock[self.node_id] = clock.get(self.node_id, 0) + 1
        self.carts[cart] = [(clock, frozenset(items))]

    def state(self, cart):
        return list(self.carts[cart])

    def merge(self, cart, theirs):
        self.carts[cart] = ref.keep_newest(self.carts.get(cart, []) + list(theirs))


class TwoPhaseSet(ref.CartNode):  # a CRDT, but its tombstones are items, not tags: a re-add is lost
    def items(self, cart):
        added, removed = self.carts.get(cart, (set(), set()))
        return added - removed

    def add(self, cart, item):
        self.carts.setdefault(cart, (set(), set()))[0].add(item)

    def remove(self, cart, item):
        self.carts.setdefault(cart, (set(), set()))[1].add(item)

    def state(self, cart):
        added, removed = self.carts[cart]
        return set(added), set(removed)

    def merge(self, cart, theirs):
        added, removed = self.carts.setdefault(cart, (set(), set()))
        added |= theirs[0]
        removed |= theirs[1]


class PushOnly(ref.CartNode):  # an ORSet, but no anti-entropy: a cart nobody writes after the heal stays apart
    async def gossip(self):
        return


class Chatty(ref.CartNode):  # an ORSet, gossiping every cart to every peer ten times a second
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.every(0.1, self.gossip)


def module(cls):
    return type(cls.__name__, (), {"CartNode": cls})


VCLOCKS, TWO_PHASE, PUSH_ONLY, CHATTY = map(module, (VectorClocks, TwoPhaseSet, PushOnly, Chatty))
LOST, BACK, SYNC, MSGS = range(4)


@functools.cache
def world_of(v, minutes=1, seed=1):
    return build_world("vector_clocks_crdts", v, minutes, seed=seed)


def first(v, seed=1):
    return [r.ok for r in world_of(v, seed=seed).runs[v].settled[0]]


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_last_write_wins_loses_adds_when_the_network_heals():
    world = world_of("main")
    assert first("main")[LOST] is False and world.stage_index("main") == 0
    run = world.runs["main"]
    reads = [o for o in run.rows("ops", 0, 60) if o[1] == scenario.READ]
    assert sum(1 for o in reads if o[7] == scenario.LOST) > 5  # devices see their adds gone


@starting_code
def test_stage_variants_land_on_their_stage_on_several_days():
    # 0 last write wins (or tombstones by item), 1 vector clocks (or a CRDT that does not converge
    # or talks too much), 2 a CRDT that gossips every second
    cases = ((TWO_PHASE, 0), (VCLOCKS, 1), (PUSH_ONLY, 1), (CHATTY, 1), ("reference", 2))
    for seed in (1, 2, 3):
        assert world_of("main", seed=seed).stage_index("main") == 0
        for v, stage in cases:
            world = world_of(v, seed=seed)
            assert world.stage_index(v) == stage, (getattr(v, "__name__", v), seed, results(world, v))


def test_each_goal_catches_its_mistake():
    assert first(VCLOCKS) == [True, False, True, True]  # nothing lost, but removes come back
    assert first(TWO_PHASE) == [False, True, True, True]  # a product added again stays removed
    assert first(PUSH_ONLY) == [True, True, False, True]  # apart until someone writes the cart
    assert first(CHATTY) == [True, True, True, False]


@starting_code
def test_a_clock_jump_loses_adds_with_last_write_wins_but_not_with_vector_clocks():
    for v in ("main", VCLOCKS):
        world = build_world("vector_clocks_crdts", v, 4)
        skews = [r for kind, r in results(world, v) if kind == "skew"]
        assert skews and all(r[LOST] is (v is VCLOCKS) for r in skews), skews


def test_reference_passes_every_goal_for_ten_minutes():
    kinds = set()
    for seed in (1, 4):
        world = build_world("vector_clocks_crdts", "reference", 10, seed=seed)
        res = results(world, "reference")
        assert len(res) >= 7 and all(all(r) for _, r in res), res
        assert world.stage_index("reference") == 2
        kinds |= {kind for kind, _ in res}
    assert kinds == {k.name for k in scenario.KINDS}


def test_incidents_are_random_but_the_first_splits_the_network_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "partition") for i in firsts)
    assert all(scenario.groups_for(i, s) == [[0, 1], [2, 3, 4]] for i, s in zip(firsts, (1, 2, 9)))
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"partition", "offline", "skew"} and all(i.cause for i in later)
    offline = [scenario.groups_for(i, 4) for i in later if i.kind == "offline"]
    assert all(len(g[0]) == 1 for g in offline) and len({g[0][0] for g in offline}) > 2
    skews = [scenario.skew_for(i, 4) for i in later if i.kind == "skew"]
    assert {s > 0 for _, s in skews} == {True, False} and all(10 <= abs(s) <= 30 for _, s in skews)


def test_every_cart_is_edited_from_two_replicas():
    for cart in range(scenario.CARTS):
        assert scenario.home(cart, 0) != scenario.home(cart, 1)
    pairs = {(scenario.home(c, 0), scenario.home(c, 1)) for c in range(scenario.CARTS)}
    assert len(pairs) == scenario.NODES * (scenario.NODES - 1)


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("vector_clocks_crdts", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["ops"] == sorted(run.keys["ops"]) and run.keys["ops"][0] >= 60
    pieces = itertools.islice(scenario.stream("reference"), 7)
    ops = sum(len(p["tables"]["ops"]) for p in pieces)
    assert run.total("served", 1e9) + run.total("failed", 1e9) == ops


# ------------------------------------------------------------- your code


@your_code(1, "compare tells before, after, equal and concurrent apart")
def test_stage1_compare():
    assert code.compare({"n0": 1}, {"n0": 1}) == "equal"
    assert code.compare({"n0": 1}, {"n0": 1, "n1": 2}) == "before"
    assert code.compare({"n0": 2, "n1": 2}, {"n0": 1}) == "after"
    assert code.compare({"n0": 2}, {"n1": 1}) == "concurrent"
    assert code.compare({}, {"n3": 1}) == "before"
    assert code.compare({"n0": 1, "n1": 0}, {"n0": 1}) == "equal"


@your_code(1, "keep_newest keeps concurrent versions as siblings and drops the old ones")
def test_stage1_keep_newest():
    a, b, c = ({"n0": 1}, frozenset("a")), ({"n0": 2}, frozenset("b")), ({"n0": 1, "n1": 1}, frozenset("c"))
    assert code.keep_newest([a, b]) == [b] and code.keep_newest([b, a]) == [b]
    assert sorted(code.keep_newest([a, b, c, a]), key=str) == sorted([b, c], key=str)
    assert len(code.keep_newest([b, (dict(b[0]), b[1])])) == 1  # the same version twice: kept once


@your_code(1, "no acknowledged add lost on the first incident")
def test_stage1_nothing_lost():
    assert first(variant())[LOST] is True


@your_code(2, "an ORSet: unique tags, observed removes, merges in any order")
def test_stage2_orset():
    a, b = code.ORSet(), code.ORSet()
    a.add("milk", "n0:1")
    b.merge(a.copy())
    b.remove("milk")  # b saw n0:1 and removes it ...
    a.add("milk", "n0:2")  # ... while a adds milk again: b never saw this one
    a.add("eggs", "n0:3")
    snapshot = a.copy()
    a.merge(b.copy())
    b.merge(snapshot)
    b.merge(snapshot)  # twice: nothing changes
    assert a.items() == b.items() == {"milk", "eggs"}  # the add b had not seen wins
    a.remove("milk")
    b.merge(a.copy())
    assert b.items() == {"eggs"} and a.items() == {"eggs"}
    old = code.ORSet()
    old.add("milk", "n0:1")  # an old copy that still has the first add ...
    b.merge(old)
    assert b.items() == {"eggs"}  # ... cannot bring it back: its tag is a tombstone


@your_code(2, "every goal on the first incident: converged, nothing lost, nothing back")
def test_stage2_every_goal():
    assert first(variant()) == [True] * 4


@starting_code
def test_both_pictures_show_the_replicas_and_the_devices():
    from live.canvas import EXTRA1, EXTRA2, EXTRA3, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    for v in ("main", "reference"):
        world = world_of(v)
        assert views_for(world) == ["peers", "cluster", "lanes"] and world.view == "peers"  # peers first
        set_view(world, "cluster")
        during = adapter_for(world).frame(v, 25.0)
        assert during.groups == [0, 0, 1, 1, 1] and during.drops  # the gossip across the cut is dropped
        assert any(c in (EXTRA1, EXTRA2, EXTRA3) for c in during.nodes)  # the two sides diverge
        text = "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
        assert during.state[0] in text
        healed = [adapter_for(world).frame(v, t) for t in (30.25, 30.5, 30.75, 31.0, 31.5)]
        red = any(RED in f.nodes for f in healed)
        assert red is (v == "main")  # last write wins: adds vanish at the heal
        set_view(world, "lanes")
        lanes = [adapter_for(world).frame(v, t, 100) for t in range(30, 40)]
        assert all(len(f.state[0]) <= 13 for f in lanes)
        assert any(c == RED for f in lanes for c, _ in f.outcomes) is (v == "main")
        set_view(world, "peers")  # back to the one it opens with (world_of keeps the world)


@starting_code
def test_the_peers_picture_cuts_the_links_and_flashes_the_lost_adds_at_the_heal():
    from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, RED
    from live.views import adapter_for, set_view

    for v in ("main", "reference"):
        world = world_of(v)
        assert type(world).view == "peers"
        set_view(world, "peers")
        during = adapter_for(world).frame(v, 25.0, 90)
        assert during.groups == [0, 0, 1, 1, 1] and during.drops
        cut = [(a, b) for a, b, _ in during.links if during.groups[a] != during.groups[b]]
        assert len(cut) == 6  # every link between the two sides, cut
        assert any(p.outline in (EXTRA1, EXTRA2, EXTRA3) for p in during.peers)  # the two sides diverge
        assert any(p.label[0] == world.s("peer_differ", node=f"n{i}", n=k)
                   for i, (p, k) in enumerate(zip(during.peers, world.behind_at(world.runs[v], 25.0))) if k)
        healed = [adapter_for(world).frame(v, t, 90) for t in (30.25, 30.5, 30.75, 31.0)]
        assert any(f.links and f.groups is None for f in healed)  # the links light up again
        assert any(p.outline == RED for f in healed for p in f.peers) is (v == "main")  # adds vanish
        assert all(p.outline == BLUE for p in adapter_for(world).frame(v, 40.0, 90).peers)  # converged
