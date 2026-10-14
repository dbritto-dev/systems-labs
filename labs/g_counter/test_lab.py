import asyncio
import itertools

from core.contract import load
from core.net import KV, Client, KVService, Network, Node, RPCError
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.g_counter import scenario

code = load("g_counter", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Base(Node):
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.kv = KV(self, "seq-kv")

    async def get(self, key):
        try:
            return await self.kv.read(key)
        except RPCError as e:
            if e.code == 20:
                return 0
            raise


class SharedKey(Base):  # stage 1: read, add, write back
    async def on_add(self, msg):
        value = await self.get("counter")
        await self.kv.write("counter", value + msg.body["delta"])
        self.reply(msg, {"type": "add_ok"})

    async def on_read(self, msg):
        self.reply(msg, {"type": "read_ok", "value": await self.get("counter")})


class CompareAndSwap(SharedKey):  # stage 2: cas on the shared key, retry on conflict
    async def on_add(self, msg):
        while True:
            value = await self.get("counter")
            try:
                await self.kv.cas("counter", value, value + msg.body["delta"], create=True)
                break
            except RPCError as e:
                if e.code != 22:
                    raise
        self.reply(msg, {"type": "add_ok"})


class KeyPerNode(Base):  # stage 3, as most people first write it: own key, one write per add
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.mine = 0

    async def on_add(self, msg):
        self.mine += msg.body["delta"]
        await self.kv.write(f"c-{self.node_id}", self.mine)
        self.reply(msg, {"type": "add_ok"})

    async def on_read(self, msg):
        values = await asyncio.gather(*(self.get(f"c-{n}") for n in self.node_ids))
        self.reply(msg, {"type": "read_ok", "value": sum(values)})


def module(cls):
    return type(cls.__name__, (), {"CounterNode": cls})


SHARED, CAS, PER_NODE = module(SharedKey), module(CompareAndSwap), module(KeyPerNode)


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_starting_code_keeps_the_count_in_memory():
    world = build_world("g_counter", "main", 1)
    assert world.stage("main") is not None
    piece = scenario.run("main", chunk=0)
    assert not [m for m in piece["tables"]["msgs"] if m[4] == scenario.KV_REQ]


def test_stage_variants_land_on_their_stage_on_every_incident():
    expected = {SHARED: (1, [True, False, True, True, False]),  # Shared key
                CAS: (2, [True, True, False, False, True]),  # Compare-and-swap
                PER_NODE: (3, [True] * 5)}  # Key per node
    for v, (stage, pattern) in expected.items():
        world = build_world("g_counter", v, 3)
        res = results(world, v)
        assert world.stage_index(v) == stage, (v.__name__, res)
        assert len(res) >= 2
        # The goals that decide each stage fail (or pass) on every incident.
        for r in res:
            assert r[:3] == pattern[:3] if v is not CAS else (r[:3] == [True, True, False]), (v.__name__, res)


def test_reference_passes_every_goal():
    world = build_world("g_counter", "reference", 4)
    res = results(world, "reference")
    assert len(res) >= 4 and all(all(r) for r in res)
    assert world.stage_index("reference") == 3  # Key per node


def test_incidents_are_random_but_the_first_is_a_burst_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "burst") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 30))
    assert {i.kind for i in later} == {"burst", "slow"} and all(i.cause for i in later)


def test_reads_carry_the_band_they_must_fall_in():
    piece = scenario.run("reference", chunk=0)
    reads = [o for o in piece["tables"]["ops"] if o[1] == scenario.READ and o[5]]
    assert reads and all(o[6] <= o[7] for o in reads)
    assert all(o[6] <= o[3] <= o[7] for o in reads)


# ------------------------------------------------------------- your code


def _cluster(cls, stale=0.5):
    net = Network(latency=0.02, jitter=0.0)
    net.join(KVService("seq-kv", stale=stale, seed=1))
    ids = ["n0", "n1", "n2"]
    nodes = [cls(i, ids) for i in ids]
    for node in nodes:
        net.join(node)
    client = Client("c1")
    net.join(client)
    return net, nodes, client


def _adds_then_read(adds: int, concurrent: bool) -> tuple[int, int]:
    async def main():
        net, nodes, client = _cluster(code.CounterNode)
        await asyncio.sleep(0.01)
        reqs = [client.rpc(f"n{i % 3}", {"type": "add", "delta": 1}, timeout=10) for i in range(adds)]
        if concurrent:
            await asyncio.gather(*reqs)
        else:
            for r in reqs:
                await r
        await asyncio.sleep(2.0)  # longer than seq-kv's lag
        values = [(await client.rpc(n, {"type": "read"}, timeout=5))["value"] for n in ("n0", "n1", "n2")]
        kv_requests = sum(1 for d in net.log if d.dest == "seq-kv")
        return values, kv_requests

    return run_virtual(main())


@your_code(1, "the count lives in seq-kv, so every node reads every add")
def test_stage1_count_is_shared():
    values, kv_requests = _adds_then_read(12, concurrent=False)
    assert kv_requests > 0 and values == [12, 12, 12]


@your_code(2, "concurrent adds are never lost")
def test_stage2_no_lost_adds():
    values, _ = _adds_then_read(30, concurrent=True)
    assert values == [30, 30, 30]


@your_code(3, "no compare-and-swap conflicts: each node writes its own key")
def test_stage3_no_conflicts():
    world = build_world("g_counter", variant(), 1)
    first = [r.ok for r in world.runs[variant()].settled[0]]
    assert first == [True] * 5


def test_a_second_picture_shows_what_the_clients_see():
    from live.views import adapter_for, set_view, views_for

    world = build_world("g_counter", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights
    text, colour = frame.state
    assert text and len(text) <= 13
