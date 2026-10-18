import functools
import itertools

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import run_virtual
from labs.merkle_anti_entropy import lab, scenario
from labs.merkle_anti_entropy import reference as ref
from labs.merkle_anti_entropy.api import HINTS, KEYS, Replica, entries, key_of

LAB = "merkle_anti_entropy"
code = load(LAB, variant(), (*scenario.NAMES, "diff", "MerkleTree", "DEPTH", "FANOUT"))


# ------------------------------------------------------------- one replica per stage, as people write them


class FullScan(ref.ReplicaNode):  # stage 1: every key's version to the next peer, every round
    async def repair(self):
        peer = self.peers[self.turn % len(self.peers)]
        self.turn += 1
        await self.full_scan(peer)


class RareScan(ref.ReplicaNode):  # a full scan once a minute: it repairs, but far too late
    async def repair(self):
        self.turn += 1
        if self.turn % 30 == 1:
            await self.full_scan(self.peers[self.turn % len(self.peers)])


class BigLeaves(ref.ReplicaNode):  # a Merkle tree with 16 leaves of 1,250 keys: one bad key streams them all
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.tree = ref.MerkleTree(self.digest, depth=1)


class Rebuild(ref.ReplicaNode):  # a Merkle tree rebuilt from all the data every round (Cassandra's validation)
    async def repair(self):
        tree = ref.MerkleTree(self.digest)
        for key, e in self.data.items():
            tree.update(key, None, e)
        self.tree = tree
        await super().repair()


def module(cls):
    return type(cls.__name__, (), {"ReplicaNode": cls})


FULL, RARE, BIG, REBUILD = map(module, (FullScan, RareScan, BigLeaves, Rebuild))
FIXED, STALE, SENT, HASHES = range(4)


@functools.cache
def world_of(v, minutes=1, seed=1):
    return build_world(LAB, v, minutes, seed=seed)


def first(v, seed=1):
    return [r.ok for r in world_of(v, seed=seed).runs[v].settled[0]]


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]], [r.value for r in run.settled[i]])
            for i in sorted(run.settled) if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_without_repair_the_replicas_stay_apart_and_reads_disagree():
    world = world_of("main")
    assert first("main")[FIXED] is False and world.stage_index("main") == 0
    run = world.runs["main"]
    late = run.rows("state", 55, 60)
    assert late and all(r[1][2] > 300 for r in late)  # n2 still misses hundreds of writes at 0:55
    reads = [o for o in run.rows("ops", 45, 60) if o[1] == scenario.READ]
    assert sum(1 for o in reads if o[4]) > 20  # and some reads get an old version


@starting_code
def test_stage_variants_land_on_their_stage_on_several_days():
    # 0 no repair (or a repair far too late), 1 a full scan (or a Merkle tree with huge leaves, or
    # one rebuilt every round), 2 a Merkle tree kept up to date
    cases = ((RARE, 0), (FULL, 1), (BIG, 1), (REBUILD, 1), ("reference", 2))
    for seed in (1, 2, 3):
        assert world_of("main", seed=seed).stage_index("main") == 0
        for v, stage in cases:
            world = world_of(v, seed=seed)
            assert world.stage_index(v) == stage, (getattr(v, "__name__", v), seed, results(world, v))


def test_each_goal_catches_its_mistake():
    assert first(RARE) == [False, False, True, True]  # not repaired in time, reads still stale
    assert first(FULL) == [True, True, False, True]  # repaired, at thousands of entries a key
    assert first(BIG) == [True, True, False, True]  # every big leaf that differs crosses whole
    assert first(REBUILD) == [True, True, True, False]  # cheap on the wire, but hashing everything


def test_reference_passes_every_goal_for_ten_minutes():
    kinds = set()
    for seed in (1, 4):
        world = build_world(LAB, "reference", 10, seed=seed)
        res = results(world, "reference")
        assert len(res) >= 7 and all(all(ok) for _, ok, _ in res), res
        assert world.stage_index("reference") == 2
        kinds |= {kind for kind, _, _ in res}
    assert kinds == {k.name for k in scenario.KINDS}


def test_incidents_are_random_but_the_first_takes_n2_down_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "down") for i in firsts)
    assert all(scenario.target(i, s) == 2 for i, s in zip(firsts, (1, 2, 9)))
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"down", "blip", "disk", "restore"} and all(i.cause for i in later)
    assert len({scenario.target(i, 4) for i in later}) == lab.REPLICAS
    spans = [scenario.key_span(i, 4) for i in later if i.kind == "restore"]
    assert all(0 <= lo and lo + n <= KEYS and 300 <= n <= 1200 for lo, n in spans)


def test_a_message_costs_its_entries():
    assert entries({"type": "ping"}) == 1
    assert entries({"type": "scan", "versions": {"k1": 3, "k2": 0}, "level": 2}) == 3
    assert entries({"type": "hashes_ok", "differ": [1, 5, 9], "note": "x"}) == 4


def test_replication_hints_and_the_hint_window():
    async def make():
        return Replica("n0", ["n0", "n1"])  # never joins a network, and its loop is gone: write() only queues

    node = run_virtual(make())
    node.load({key_of(0): (1, 10)})
    assert node.store(key_of(0), 1, 99) is False and node.store(key_of(0), 2, 20) is True
    assert node.data[key_of(0)] == (2, 20) and node.fixed == 1
    node.down_peers.add("n1")
    for i in range(HINTS + 7):
        node.write(key_of(i + 1), 100 + i, i)
    assert len(node._hints["n1"]) == HINTS and node.overflow == 7  # the rest never reach n1
    node.force(key_of(1), None)  # a bad disk
    assert node.version(key_of(1)) == 0


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world(LAB, "reference", 7)
    run = world.runs["reference"]
    assert run.keys["ops"] == sorted(run.keys["ops"]) and run.keys["ops"][0] >= 60
    pieces = list(itertools.islice(scenario.stream("reference"), 7))
    reads = sum(1 for p in pieces for o in p["tables"]["ops"] if o[1] == scenario.READ)
    assert run.total("reads", 1e9) == reads
    assert sum(len(p["tables"]["state"]) for p in pieces) == 7 * 60 / scenario.SAMPLE


# ------------------------------------------------------------- your code


@your_code(1, "diff finds the keys each side has newer")
def test_stage1_diff():
    need, give = code.diff({"k1": 5, "k2": 3}, {"k1": 4, "k2": 7, "k3": 1})
    assert sorted(need) == ["k2", "k3"] and sorted(give) == ["k1"]
    assert code.diff({"k1": 2}, {"k1": 2}) == ([], [])
    assert code.diff({}, {}) == ([], [])


@your_code(1, "the first incident repaired in time, and reads agree afterwards")
def test_stage1_repaired():
    ok = first(variant())
    assert ok[FIXED] and ok[STALE]


@your_code(2, "a Merkle tree: leaves cover the key range, and one change touches one path")
def test_stage2_merkle_tree():
    work = [0]

    def digest(*parts):
        work[0] += len(parts)
        return hash(parts)

    a, b = code.MerkleTree(digest), code.MerkleTree(digest)
    leaves = a.leaves
    covered = [k for leaf in range(leaves) for k in a.keys_of(leaf)]
    assert covered == [key_of(i) for i in range(KEYS)]  # every key once, in order
    assert all(a.leaf_of(k) == leaf for leaf in (0, leaves // 2, leaves - 1) for k in a.keys_of(leaf))
    assert 1 <= KEYS / leaves <= 64  # a sensible leaf: a handful of keys
    assert list(a.children(0)) == list(range(a.fanout))
    for i in range(0, KEYS, 7):
        a.update(key_of(i), None, (i, 1))
        b.update(key_of(i), None, (i, 1))
    assert a.hash(0, 0) == b.hash(0, 0)
    b.update(key_of(700), (700, 1), (900, 2))
    assert a.hash(0, 0) != b.hash(0, 0)
    path = [a.leaf_of(key_of(700)) // a.fanout ** (a.depth - d) for d in range(a.depth + 1)]
    for d in range(a.depth + 1):
        differ = [i for i in range(a.fanout ** d) if a.hash(d, i) != b.hash(d, i)]
        assert differ == [path[d]], (d, differ)
    b.update(key_of(700), (900, 2), (700, 1))  # back to the same: the same hashes again
    assert a.hash(0, 0) == b.hash(0, 0)
    work[0] = 0
    a.update(key_of(5), None, (5, 5))
    a.hash(0, 0)
    assert work[0] <= 8 + a.depth * a.fanout  # one leaf and its ancestors, not the whole tree


@your_code(2, "every goal on the first incident: repaired, fresh reads, a few entries a key, little hashing")
def test_stage2_every_goal():
    assert first(variant()) == [True] * 4


@starting_code
def test_both_pictures_show_the_replicas_and_the_clients():
    from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    for v in ("main", "reference"):
        world = world_of(v)
        assert views_for(world) == ["peers", "cluster", "lanes"]  # peers first: it opens with it
        set_view(world, "cluster")
        during = adapter_for(world).frame(v, 25.0)
        assert during.groups == [1, 1, 0, 1] and during.nodes[2] == RED  # n2 is down ...
        drops = [adapter_for(world).frame(v, 21 + k / 4).drops for k in range(32)]
        assert any(drops) is (v == "reference")  # ... and the repair rounds to it are lost
        text = "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
        assert during.state[0] in text
        after = adapter_for(world).frame(v, 31.0)
        assert after.nodes[2] in (EXTRA1, EXTRA2, EXTRA3)  # back, but missing writes
        late = adapter_for(world).frame(v, 50.0)
        assert (late.nodes == [BLUE] * 4) is (v == "reference")  # repaired, or orange for good
        repair = [f for t in (31.0, 31.5, 32.0, 32.5, 33.0, 34.0) for f in adapter_for(world).frame(v, t).flights
                  if f[3] in (EXTRA1, EXTRA2, EXTRA3)]
        assert bool(repair) is (v == "reference")  # orange repair messages fly
        set_view(world, "lanes")
        lanes = [adapter_for(world).frame(v, t, 100) for t in range(40, 55)]
        assert all(len(f.state[0]) <= 13 for f in lanes)
        assert any(c == RED for f in lanes for c, _ in f.outcomes) is (v == "main")  # stale reads
        set_view(world, "peers")


@starting_code
def test_the_peers_picture_shows_the_replica_down_its_links_cut_and_the_repair_on_them():
    from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, RED, plain
    from live.frame import compose
    from live.views import adapter_for
    from live.worlds.merkle_anti_entropy import diverged_at

    def peers(v, times):
        world = world_of(v) if isinstance(v, str) else build_world(LAB, v, 1)
        assert world.view == "peers"
        return world, [adapter_for(world).frame(v, t, 90) for t in times]

    for v in ("main", "reference"):
        world, (during,) = peers(v, [25.0])
        n2 = during.peers[2]
        assert n2.outline == RED and n2.label[0] == "n2"  # down: red, no word
        assert during.groups == [1, 1, 0, 1]
        assert {(0, 2), (1, 2), (2, 3)} <= {(a, b) for a, b, _ in during.links}  # its three links, cut
        assert "✕" in "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
    repair = (EXTRA1, EXTRA2, EXTRA3)
    after = [k / 4 for k in range(124, 140)]  # 0:31 to 0:35, once n2 is back
    _, given = peers("main", after)
    _, solved = peers("reference", after)
    _, scan = peers(FULL, after)
    missing = diverged_at(world_of("main").runs["main"], after[0])[2]
    assert missing > 300 and given[0].peers[2].label[0] == world.s("peer_missing", node="n2", n=missing)
    assert given[0].peers[2].outline in repair  # back, missing the writes it slept through
    assert not any(c in repair for f in given for _, _, c in f.links)  # the starting code never repairs ...
    _, late = peers("main", [50.0])
    assert late[0].peers[2].outline in repair  # ... so n2 stays behind
    _, late = peers("reference", [50.0])
    assert [p.outline for p in late[0].peers] == [BLUE] * 4  # repaired

    def touching(frames, colours) -> bool:  # a link to n2 in one of these colours
        return any(c in colours and 2 in (a, b) for f in frames for a, b, c in f.links)

    assert touching(solved, repair) and not touching(solved, (EXTRA3,))  # Merkle: a short, light burst to n2
    assert sum(touching([f], (EXTRA3,)) for f in scan) >= len(scan) // 4  # a full scan: a deep orange stream
    _, calm = peers("reference", [k / 2 for k in range(10, 36)])  # 0:05 to 0:18: hashing under the goal
    assert any(p.fill > 0 for f in calm for p in f.peers) and all(p.fill < 1 for f in calm for p in f.peers)
    _, rebuild = peers(REBUILD, [k / 2 for k in range(10, 36)])
    assert any(p.fill == 1.0 and p.gauge == EXTRA2 for f in rebuild for p in f.peers)  # rebuilding: far over it
