import itertools

from core.contract import load
from core.net import Node
from core.testing import build_world, starting_code, variant, your_code
from labs.broadcast import scenario

code = load("broadcast", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Base(Node):
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.messages, self.neighbours = set(), []

    async def on_topology(self, msg):
        self.neighbours = msg.body["topology"][self.node_id]
        self.reply(msg, {"type": "topology_ok"})

    async def on_read(self, msg):
        self.reply(msg, {"type": "read_ok", "messages": sorted(self.messages)})

    async def on_broadcast(self, msg):
        self.reply(msg, {"type": "broadcast_ok"})
        self.got(msg.body["message"], None)


class Flood(Base):  # stage 1: tell the neighbours, fire and forget
    async def on_gossip(self, msg):
        self.got(msg.body["message"], msg.src)

    def got(self, v, src):
        if v not in self.messages:
            self.messages.add(v)
            for n in self.neighbours:
                if n != src:
                    self.send(n, {"type": "gossip", "message": v})


class FloodRetry(Base):  # stage 2: tell the neighbours, re-send until acknowledged
    async def on_gossip(self, msg):
        self.reply(msg, {"type": "gossip_ok"})
        self.got(msg.body["message"], msg.src)

    def got(self, v, src):
        if v not in self.messages:
            self.messages.add(v)
            for n in self.neighbours:
                if n != src:
                    self.spawn(self.push(n, v))

    async def push(self, n, v):
        while True:
            try:
                await self.rpc(n, {"type": "gossip", "message": v}, timeout=0.5)
                return
            except TimeoutError:
                await self.sleep(0.2)


class Direct(FloodRetry):  # stage 3: straight to every node, re-send until acknowledged
    def got(self, v, src):
        if v not in self.messages:
            self.messages.add(v)
            if src is None:
                for n in self.node_ids:
                    if n != self.node_id:
                        self.spawn(self.push(n, v))


def module(cls):
    return type(cls.__name__, (), {"BroadcastNode": cls})


FLOOD, FLOOD_RETRY, DIRECT = module(Flood), module(FloodRetry), module(Direct)


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_a_single_node_keeps_numbers_to_itself():
    world = build_world("broadcast", "main", 1)
    assert world.stage("main") is not None
    piece = scenario.run("main", chunk=0)
    assert piece["tables"]["values"] and not [d for d in piece["tables"]["done"] if d[2]]


def test_stage_variants_land_on_their_stage():
    # 1 multi-node, 2 fault tolerant, 3 efficient
    for v, stage in ((FLOOD, 1), (FLOOD_RETRY, 2), (DIRECT, 3)):
        world = build_world("broadcast", v, 2)
        assert world.stage_index(v) == stage, (v.__name__, results(world, v))


def test_flooding_loses_numbers_in_every_partition():
    world = build_world("broadcast", FLOOD, 3)
    res = results(world, FLOOD)
    assert len(res) >= 3 and all(r[0] and not r[1] for r in res)


def test_reference_passes_every_goal():
    world = build_world("broadcast", "reference", 4)
    res = results(world, "reference")
    assert len(res) >= 4 and all(all(r) for r in res)
    assert world.stage_index("reference") == 4  # batched


def test_partitions_are_random_but_the_first_splits_the_cluster_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "split") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 30))
    assert {i.kind for i in later} == {"split", "isolate"} and all(i.cause for i in later)
    ids = [f"n{i}" for i in range(25)]
    for inc in later:
        groups = scenario.groups_for(inc, ids, 4)
        assert len(groups) == 2 and sum(map(len, groups)) == 25 and all(groups)


# ------------------------------------------------------------- your code


def first(v=None):
    v = v or variant()
    return [r.ok for r in build_world("broadcast", v, 1).runs[v].settled[0]]


@your_code(1, "numbers reach every node")
def test_stage1_numbers_reach_every_node():
    assert first()[0]


@your_code(2, "numbers sent during a partition arrive after it heals")
def test_stage2_survives_partitions():
    assert first()[:2] == [True, True]


@your_code(3, "under 30 messages per operation, p50 < 400 ms, max < 600 ms")
def test_stage3_efficient():
    assert first()[:4] == [True] * 4


@your_code(4, "under 20 messages per operation, p50 < 1 s, max < 2 s")
def test_stage4_batched():
    assert first() == [True] * 6


def test_a_second_picture_shows_what_the_clients_see():
    from live.views import adapter_for, set_view, views_for

    world = build_world("broadcast", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights
    text, colour = frame.state
    assert text and len(text) <= 13
