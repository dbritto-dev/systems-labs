import itertools

from core.contract import load
from core.net import Node
from core.testing import build_world, variant, your_code
from labs.unique_ids import scenario

code = load("unique_ids", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Echo(Node):
    async def on_echo(self, msg):
        self.reply(msg, {"type": "echo_ok", "echo": msg.body["echo"]})


class Counter(Echo):  # a counter per node: collides across nodes
    def __init__(self, i, ids):
        super().__init__(i, ids)
        self.n = 0

    async def on_generate(self, msg):
        self.n += 1
        self.reply(msg, {"type": "generate_ok", "id": self.n})


class Leader(Counter):  # unique, but asks n0: unavailable when cut off from it
    async def on_next(self, msg):
        self.n += 1
        self.reply(msg, {"type": "next_ok", "n": self.n})

    async def on_generate(self, msg):
        if self.node_id == "n0":
            self.n += 1
            self.reply(msg, {"type": "generate_ok", "id": self.n})
            return
        reply = await self.rpc("n0", {"type": "next"}, timeout=0.8)
        self.reply(msg, {"type": "generate_ok", "id": reply["n"]})


class NodeCounter(Counter):  # stage 2: node + counter, as a string
    async def on_generate(self, msg):
        self.n += 1
        self.reply(msg, {"type": "generate_ok", "id": f"{self.node_id}-{self.n}"})


class IntCounter(Counter):  # 64-bit and unique, but not ordered by time
    async def on_generate(self, msg):
        self.n += 1
        self.reply(msg, {"type": "generate_ok", "id": int(self.node_id[1:]) * 10**12 + self.n})


class NaiveSnowflake(Echo):  # ordered by time, but trusts the clock when it steps back
    def __init__(self, i, ids):
        super().__init__(i, ids)
        self.last, self.seq = -1, 0

    async def on_generate(self, msg):
        ms = self.wall_ms() - 1_735_689_600_000
        self.seq = self.seq + 1 if ms == self.last else 0
        self.last = ms
        self.reply(msg, {"type": "generate_ok", "id": (ms << 22) | (int(self.node_id[1:]) << 12) | self.seq})


def module(cls):
    return type(cls.__name__, (), {"UniqueIdNode": cls})


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_the_starting_node_answers_nothing():
    world = build_world("unique_ids", "main", 1)
    assert world.stage_index("main") == 0  # Nothing yet


def test_stage_variants_land_on_their_stage_every_time():
    expect = {Echo: 1, Counter: 1, Leader: 1, NodeCounter: 2, IntCounter: 2, NaiveSnowflake: 2}  # 1 Echo, 2 Unique IDs
    for cls, stage in expect.items():
        v = module(cls)
        world = build_world("unique_ids", v, 2)
        assert world.stage_index(v) == stage, cls.__name__


def test_why_each_wrong_answer_fails():
    def first(cls):
        v = module(cls)
        return results(build_world("unique_ids", v, 1), v)[0]

    assert first(Counter)[:3] == [True, False, True]  # duplicates
    assert first(Leader)[:3] == [True, True, False]  # not available while cut off
    assert first(NodeCounter)[3:5] == [False, False]  # not a 64-bit int
    assert first(IntCounter)[3:5] == [True, False]  # not ordered by time
    assert first(NaiveSnowflake)[3:] == [True, True, False]  # went backwards with the clock


def test_reference_passes_every_goal():
    world = build_world("unique_ids", "reference", 4)
    res = results(world, "reference")
    assert len(res) >= 4 and all(all(r) for r in res)
    assert world.stage_index("reference") == 3  # Snowflake IDs


def test_incidents_are_random_but_the_first_is_a_migration_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "migrate") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"split", "clock", "migrate"} and all(i.cause for i in later)


# ------------------------------------------------------------- your code


def first():
    v = variant()
    return [r.ok for r in build_world("unique_ids", v, 1).runs[v].settled[0]]


@your_code(1, "echo replies with the same message")
def test_stage1_echo():
    assert first()[0]


@your_code(2, "ids are unique across nodes and available during a partition")
def test_stage2_unique_and_available():
    assert first()[:3] == [True, True, True]


@your_code(3, "ids are 64-bit ints, ordered by time, never going backwards")
def test_stage3_snowflake():
    assert first() == [True] * 6
