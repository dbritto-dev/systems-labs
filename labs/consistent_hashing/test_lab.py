import bisect
import itertools

import pytest

from core.contract import load
from core.i18n import lab_text
from core.testing import build_world, variant, your_code
from labs.consistent_hashing import lab, scenario
from labs.consistent_hashing.main import stable_hash

code = load("consistent_hashing", variant(), scenario.NAMES)
NODES = [f"c{i}" for i in range(8)]
KEYS = [f"k{i}" for i in range(20_000)]


class MODULO:  # stage 0, the given code: hash(key) % N
    class Router:
        def __init__(self, nodes):
            self.nodes = list(nodes)

        def add(self, node):
            self.nodes.append(node)

        def remove(self, node):
            self.nodes.remove(node)

        def node_for(self, key):
            return self.nodes[stable_hash(key) % len(self.nodes)]


class RING:  # stage 1: one point per node on a hash ring
    class Router:
        def __init__(self, nodes):
            self.ring = sorted((stable_hash(n), n) for n in nodes)

        def add(self, node):
            bisect.insort(self.ring, (stable_hash(node), node))

        def remove(self, node):
            self.ring = [p for p in self.ring if p[1] != node]

        def node_for(self, key):
            i = bisect.bisect_left(self.ring, (stable_hash(key), ""))
            return self.ring[i % len(self.ring)][1]


class WRONG:  # returns a node that is not in the cluster any more
    class Router(MODULO.Router):
        def remove(self, node):
            pass


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_the_first_change_is_a_node_dying_at_0_20():
    for seed in (1, 2, 99):
        first = next(scenario.incidents(seed))
        assert (first.t0, first.kind) == (20.0, "crash")
        assert scenario.victim(first, seed) == scenario.victim(first, seed) in NODES
    kinds = {i.kind for i in itertools.islice(scenario.incidents(3), 30)}
    assert kinds == {"crash", "scale", "deploy"}


def test_modulo_moves_most_keys_and_floods_the_database():
    world = build_world("consistent_hashing", MODULO, 1)
    assert results(world, MODULO)[0] == [True, False, False, False]  # even, but 7/N moved
    assert world.stage_index(MODULO) == 0


def test_a_ring_moves_few_keys_but_spreads_them_unevenly():
    world = build_world("consistent_hashing", RING, 1)
    assert results(world, RING)[0] == [False, True, True, True]
    assert world.stage_index(RING) == 1


def test_reference_passes_every_goal_on_every_change():
    world = build_world("consistent_hashing", "reference", 4)
    found = results(world, "reference")
    kinds = {world.runs["reference"].incidents[i].kind for i in range(len(found))}
    assert len(found) >= 4 and kinds == {"crash", "scale", "deploy"}
    assert all(all(r) for r in found)
    assert world.stage_index("reference") == 2


def test_the_events_name_the_node():
    world = build_world("consistent_hashing", MODULO, 1)
    run = world.runs[MODULO]
    victim = scenario.victim(next(scenario.incidents(1)), 1)
    starts = [e for e in run.timeline if e.kind in ("start", "end")]
    assert starts and all(victim in e.text for e in starts)


def test_pieces_join_in_order_and_totals_survive():
    world = build_world("consistent_hashing", MODULO, 2)
    run = world.runs[MODULO]
    assert run.keys["reads"] == sorted(run.keys["reads"])
    pieces = list(itertools.islice(scenario.stream(MODULO), 2))
    assert run.total("reads", 1e9) == sum(len(p["tables"]["reads"]) for p in pieces)
    assert all(-1e-9 < c[0] < 120 for p in pieces for c in p["tables"]["changes"])


def test_a_router_that_returns_a_node_not_in_the_cluster_is_reported():
    with pytest.raises(ValueError, match="node_for"):
        scenario.run(WRONG, chunk=0)
    assert "{node}" in lab_text("consistent_hashing").STRINGS["bad_node"]


# ------------------------------------------------------------- your code


def owners(router):
    return {k: router.node_for(k) for k in KEYS}


@your_code(1, "removing a node moves only that node's keys")
def test_stage1_remove_moves_only_its_keys():
    r = code.Router(list(NODES))
    before = owners(r)
    r.remove("c3")
    after = owners(r)
    moved = [k for k in KEYS if before[k] != after[k]]
    assert all(before[k] == "c3" for k in moved)
    assert "c3" not in after.values()


@your_code(1, "adding a node moves keys only to the new node")
def test_stage1_add_moves_keys_only_to_it():
    r = code.Router(list(NODES))
    before = owners(r)
    r.add("c8")
    after = owners(r)
    moved = [k for k in KEYS if before[k] != after[k]]
    assert moved and all(after[k] == "c8" for k in moved)
    assert len(moved) <= lab.MOVED_MAX * len(KEYS) / 9


@your_code(2, f"every node owns at most {lab.BALANCE_MAX}x its share of keys")
def test_stage2_keys_are_spread_evenly():
    for nodes in (NODES, NODES[:6], NODES + ["c8"]):
        r = code.Router(list(nodes))
        counts = {n: 0 for n in nodes}
        for k in KEYS:
            counts[r.node_for(k)] += 1
        assert max(counts.values()) / (len(KEYS) / len(nodes)) <= lab.BALANCE_MAX
        before = owners(r)
        r.remove(nodes[0])
        moved = sum(before[k] != r.node_for(k) for k in KEYS)
        assert moved <= lab.MOVED_MAX * len(KEYS) / len(nodes)  # still a ring


@your_code(2, "the first change passes every goal")
def test_stage2_first_change_passes():
    world = build_world("consistent_hashing", variant(), 1)
    assert results(world, variant())[0] == [True, True, True, True]
