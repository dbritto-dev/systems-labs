import functools
import itertools

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.chain_replication import reference as ref
from labs.chain_replication import scenario

code = load("chain_replication", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Chain(ref.ChainNode):  # stage 1: a chain that works while nothing fails, and nothing repairs it
    async def chain_changed(self, old):
        return

    async def on_snapshot(self, msg):
        self.reply(msg, {"type": "snapshot_ok", "store": dict(self.store), "seq": self.seq})


class NoCopying(ref.ChainNode):  # repairs, but the tail forgets what it applies while a node copies it
    async def on_snapshot(self, msg):
        self.reply(msg, {"type": "snapshot_ok", "store": dict(self.store), "seq": self.seq})


class StopAndWait(ref.ChainNode):  # repairs, but the head sends the next write only once the last is acked
    def __init__(self, *args):
        super().__init__(*args)
        self.queue = []

    async def on_put(self, msg):
        self.queue.append(msg)
        if len(self.queue) == 1:
            self.next_write()

    def next_write(self):
        if self.queue:
            msg = self.queue[0]
            self.apply({"seq": self.seq + 1, "key": msg.body["key"], "value": msg.body["value"],
                        "client": msg.src, "req": msg.body["msg_id"]})

    async def on_ack(self, msg):
        await super().on_ack(msg)
        if self.predecessor() is None and self.queue:
            self.queue.pop(0)
            self.next_write()


def read_any(chain, rng):  # reads spread over every node, as in primary-backup
    return rng.choice(chain)


def module(cls, read_from=ref.read_from):
    return type(cls.__name__, (), {"ChainNode": cls, "read_from": staticmethod(read_from)})


CHAIN, NO_COPYING, STOP_AND_WAIT = map(module, (Chain, NoCopying, StopAndWait))
CHAIN_READ_ANY = module(Chain, read_any)  # a chain, but reads from any node: some see a write that is then lost
STALE, LOST, OUTAGE, REPLICAS, P99 = range(5)
SEEDS = (1, 2, 3)


@functools.cache
def world_of(v, minutes=1, seed=1):
    return build_world("chain_replication", v, minutes, seed=seed)


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_primary_backup_reads_miss_acknowledged_writes():
    piece = scenario.run("main", chunk=0)
    gets = [o for o in piece["tables"]["ops"] if o[1] == scenario.GET and o[5]]
    assert gets and any(o[6] for o in gets if o[0] < 20.0)  # stale even before anything fails
    for seed in SEEDS:
        assert world_of("main", seed=seed).stage_index("main") == 0


def test_primary_backup_loses_acknowledged_writes_when_the_head_dies():
    res = results(world_of("main", 4, 3), "main")
    heads = [r for kind, r in res if kind == "head"]
    assert heads and all(not r[LOST] for r in heads)


def test_stage_variants_land_on_their_stage():
    # 0 a chain read from any node; 1 a chain (it stalls at a failure), a repair that stalls the node that
    # joins, or one that sends one write at a time
    for v, stage in ((CHAIN_READ_ANY, 0), (CHAIN, 1), (NO_COPYING, 1), (STOP_AND_WAIT, 1)):
        for seed in SEEDS:
            world = world_of(v, seed=seed)
            assert world.stage_index(v) == stage, (v.__name__, seed, results(world, v))


def test_each_goal_catches_its_mistake():
    (_, chain), = results(world_of(CHAIN), CHAIN)
    assert chain[STALE] and chain[LOST] and not chain[OUTAGE]
    (_, nocopy), = results(world_of(NO_COPYING), NO_COPYING)
    assert nocopy[STALE] and nocopy[LOST] and not nocopy[REPLICAS]
    (_, saw), = results(world_of(STOP_AND_WAIT), STOP_AND_WAIT)
    assert not saw[P99]


def test_reference_passes_every_goal():
    for seed in (1, 3):
        world = build_world("chain_replication", "reference", 10, seed=seed)
        res = results(world, "reference")
        assert len(res) >= 5 and all(all(r) for _, r in res), res
        assert {kind for kind, _ in res} >= {"head", "middle", "slow"}
        assert world.stage_index("reference") == 2


def test_incidents_are_random_but_the_first_crashes_n1_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "middle") for i in firsts)
    chain = ["n0", "n1", "n2", "n3"]
    assert all(scenario.victim(i, chain, s) == "n1" for i, s in zip(firsts, (1, 2, 9)))
    later = list(itertools.islice(scenario.incidents(4), 30))
    assert {i.kind for i in later} == {"head", "middle", "tail", "slow"} and all(i.cause for i in later)
    heads = [i for i in later if i.kind == "head"]
    assert all(scenario.victim(i, chain, 4) == "n0" for i in heads)


# ------------------------------------------------------------- your code


def first(v=None):
    v = v or variant()
    return [r.ok for r in world_of(v).runs[v].settled[0]]


@your_code(1, "a chain: no stale reads, no lost writes")
def test_stage1_chain():
    assert first()[:2] == [True, True]


@your_code(2, "repair: writes back within 3 s, the node that joins in sync, p99 under 500 ms")
def test_stage2_repair():
    assert first() == [True] * 5


# ------------------------------------------------------------- the pictures


def test_the_cluster_picture_shows_the_chain_left_to_right():
    from live.canvas import RED
    from live.views import adapter_for, views_for

    world = build_world("chain_replication", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    before = adapter_for(world).frame("reference", 10.0)
    assert before.columns == 4 and [w for w, _ in before.labels][0].startswith("n0")
    down = adapter_for(world).frame("reference", 20.5)  # n1 died; the master has not noticed yet
    assert down.nodes[1] == RED
    after = adapter_for(world).frame("reference", 25.0)  # n1 is out: it moved to the right
    assert after.nodes[-1] == RED and [w for w, _ in after.labels][-1].startswith("n1")
    assert any(f[3] for f in after.flights)  # messages flow along the chain


def test_a_second_picture_shows_what_the_clients_see():
    from live.canvas import RED
    from live.views import adapter_for, set_view

    world = build_world("chain_replication", "reference", 1)
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights or frame.outcomes
    text, _ = frame.state
    assert text and len(text) <= 13
    assert RED not in [c for c, _ in frame.outcomes]  # no stale reads, no lost writes
