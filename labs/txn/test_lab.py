import itertools

from core.contract import load
from core.net import Node
from core.testing import build_world, variant, your_code
from labs.txn import scenario

code = load("txn", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Single(Node):
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.store = {}

    def run(self, msg):
        result, writes = [], []
        for op, key, value in msg.body["txn"]:
            if op == "r":
                result.append(["r", key, self.store.get(key)])
            else:
                self.store[key] = value
                writes.append([key, value])
                result.append(["w", key, value])
        self.reply(msg, {"type": "txn_ok", "txn": result})
        return writes

    async def on_txn(self, msg):
        self.run(msg)


class FireAndForget(Single):  # stage 1: send each write to the others, no retries
    async def on_txn(self, msg):
        for key, value in self.run(msg):
            for n in self.node_ids:
                if n != self.node_id:
                    self.send(n, {"type": "put", "key": key, "value": value})

    async def on_put(self, msg):
        self.store[msg.body["key"]] = msg.body["value"]


class PerWrite(Single):  # stage 2: each write re-sent until acked, newest stamp wins
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.stamps, self.rank, self.counter = {}, node_ids.index(node_id), itertools.count()

    async def on_txn(self, msg):
        stamp = (self.now(), self.rank, next(self.counter))
        for key, value in self.run(msg):
            self.stamps[key] = stamp
            for n in self.node_ids:
                if n != self.node_id:
                    self.spawn(self.push(n, key, value, stamp))

    async def push(self, n, key, value, stamp):
        while True:
            try:
                await self.rpc(n, {"type": "put", "key": key, "value": value, "stamp": list(stamp)}, timeout=0.5)
                return
            except TimeoutError:
                await self.sleep(0.2)

    async def on_put(self, msg):
        key, stamp = msg.body["key"], tuple(msg.body["stamp"])
        if stamp >= self.stamps.get(key, ()):
            self.store[key], self.stamps[key] = msg.body["value"], stamp
        self.reply(msg, {"type": "put_ok"})


def module(cls):
    return type(cls.__name__, (), {"TxnNode": cls})


SINGLE, FIRE, PER_WRITE = module(Single), module(FireAndForget), module(PerWrite)


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_a_single_node_per_store_never_catches_up():
    world = build_world("txn", SINGLE, 2)
    res = results(world, SINGLE)
    assert res and all(not r[0] for r in res)
    assert world.stage(SINGLE).label == "Single node"


def test_stage_variants_land_on_their_stage_on_every_partition():
    for v, stage, expected in ((FIRE, "Replicated", [True, True, False]),
                               (PER_WRITE, "Read uncommitted", [True, True, True, False])):
        world = build_world("txn", v, 3)
        res = results(world, v)
        assert len(res) >= 3, res
        assert all(r[:len(expected)] == expected for r in res), (v.__name__, res)
        assert world.stage(v).label == stage


def test_reference_passes_every_goal():
    world = build_world("txn", "reference", 4)
    res = results(world, "reference")
    assert len(res) >= 4 and all(all(r) for r in res)
    assert world.stage("reference").label == "Read committed"


def test_partitions_are_random_but_the_first_cuts_a_node_off_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "isolate") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 20))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET and len({i.cause for i in later}) > 1


def test_the_trace_stays_bounded():
    pieces = scenario.stream("reference")
    for _ in range(3):
        piece = next(pieces)
    sizes = {k: len(v) for k, v in piece["tables"].items()}
    pieces.close()
    assert sizes["txns"] < 4000 and sizes["msgs"] < 15000 and sizes["stale"] <= 600


# ------------------------------------------------------------- your code


def first():
    v = variant()
    return [r.ok for r in build_world("txn", v, 1).runs[v].settled[0]]


@your_code(1, "writes reach the other nodes")
def test_stage1_replicates():
    assert first()[0]


@your_code(2, "every node catches up after a partition")
def test_stage2_catches_up():
    assert first()[:3] == [True, True, True]


@your_code(3, "no intermediate reads (read committed)")
def test_stage3_read_committed():
    assert first() == [True] * 4
