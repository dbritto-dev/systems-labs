import asyncio
import itertools
import random

from core.contract import load
from core.net import KV, Client, KVService, Network, Node, RPCError
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.kafka_log import scenario

code = load("kafka_log", variant(), scenario.NAMES)


class LinKVNode(Node):
    """Stage 1 (5b) as most people first write it: everything in lin-kv."""

    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.kv = KV(self, "lin-kv", timeout=0.5)

    async def on_send(self, msg):
        key = msg.body["key"]
        while True:
            try:
                n = await self.kv.read(f"next/{key}")
            except RPCError:
                n = 0
            try:
                await self.kv.cas(f"next/{key}", n, n + 1, create=True)
                break
            except RPCError:
                await self.sleep(random.uniform(0, 0.02))  # someone else won: back off a little
        await self.kv.write(f"msg/{key}/{n}", msg.body["msg"])
        self.reply(msg, {"type": "send_ok", "offset": n})

    async def on_poll(self, msg):
        out = {}
        for key, start in msg.body["offsets"].items():
            pairs = []
            for o in range(start, start + 5):
                try:
                    pairs.append([o, await self.kv.read(f"msg/{key}/{o}")])
                except RPCError:
                    break  # not written yet: stop here, never skip it
            out[key] = pairs
        self.reply(msg, {"type": "poll_ok", "msgs": out})

    async def on_commit_offsets(self, msg):
        for key, off in msg.body["offsets"].items():
            while True:
                try:
                    cur = await self.kv.read(f"commit/{key}")
                except RPCError:
                    cur = None
                if cur is not None and cur >= off:
                    break
                try:
                    await self.kv.cas(f"commit/{key}", cur, off, create=True)
                    break
                except RPCError:
                    continue
        self.reply(msg, {"type": "commit_offsets_ok"})

    async def on_list_committed_offsets(self, msg):
        out = {}
        for key in msg.body["keys"]:
            try:
                out[key] = await self.kv.read(f"commit/{key}")
            except RPCError:
                pass
        self.reply(msg, {"type": "list_committed_offsets_ok", "offsets": out})


class LINKV:  # stands in for a main.py module
    KafkaNode = LinKVNode


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_a_log_per_node_hands_out_the_same_offsets_twice():
    world = build_world("kafka_log", "main", 2)
    res = results(world, "main")
    assert len(res) >= 2 and all(r[:3] == [False, False, False] for r in res)
    assert world.stage_index("main") == 0  # Single node


def test_lin_kv_is_correct_but_slow_and_chatty_on_every_incident():
    world = build_world("kafka_log", LINKV, 3)
    res = results(world, LINKV)
    assert len(res) >= 2 and all(r == [True, True, True, False, False] for r in res)
    assert world.stage_index(LINKV) == 1  # Multi-node


def test_reference_passes_every_goal():
    world = build_world("kafka_log", "reference", 4)
    res = results(world, "reference")
    kinds = {i.kind for i in world.runs["reference"].incidents}
    assert len(res) >= 3 and kinds == {"burst", "slowkv"} and all(all(r) for r in res)
    assert world.stage_index("reference") == 2  # Efficient


def test_incidents_are_random_but_the_first_is_a_burst_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 5, 8)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "burst") for i in firsts)
    later = list(itertools.islice(scenario.incidents(3), 30))
    assert {i.kind for i in later} == {"burst", "slowkv"} and all(i.cause for i in later)


def test_minutes_join_and_old_offsets_are_forgotten():
    pieces = list(itertools.islice(scenario.stream("reference"), 3))
    starts = [o[0] for p in pieces for o in p["tables"]["ops"]]
    assert starts == sorted(starts) and pieces[-1]["end"] == 180.0
    world = build_world("kafka_log", "reference", 3)
    assert world.runs["reference"].pieces == 3


# ------------------------------------------------------------- your code


def cluster(node_cls):
    net = Network(latency=0.01, jitter=0.0)
    net.join(KVService("lin-kv"))
    ids = ["n0", "n1"]
    nodes = [node_cls(i, ids) for i in ids]
    for n in nodes:
        net.join(n)
    client = Client("c1")
    net.join(client)
    return client


@your_code(1, "two nodes never hand out the same offset")
def test_stage1_offsets_are_unique_across_nodes():
    async def main():
        c = cluster(code.KafkaNode)
        offsets = []
        for wave in range(10):  # 4 at a time, on both nodes: correctness, not speed
            sends = [c.rpc(f"n{i % 2}", {"type": "send", "key": "k1", "msg": wave * 4 + i}, timeout=10)
                     for i in range(4)]
            offsets += [r["offset"] for r in await asyncio.gather(*sends)]
        return offsets

    offsets = run_virtual(main())
    assert len(set(offsets)) == len(offsets)


@your_code(1, "a poll on either node sees every message, in offset order")
def test_stage1_both_nodes_serve_every_message():
    async def main():
        c = cluster(code.KafkaNode)
        acked = [(await c.rpc(f"n{i % 2}", {"type": "send", "key": "k2", "msg": 100 + i}, timeout=10))["offset"]
                 for i in range(6)]
        polls = [await c.rpc(n, {"type": "poll", "offsets": {"k2": 0}}, timeout=10) for n in ("n0", "n1")]
        return acked, polls

    acked, polls = run_virtual(main())
    for p in polls:
        got = [o for o, _ in p["msgs"]["k2"]]
        assert got == sorted(got) and got == sorted(acked)[: len(got)] and got


@your_code(1, "committed offsets are shared and never go back")
def test_stage1_commits():
    async def main():
        c = cluster(code.KafkaNode)
        await c.rpc("n0", {"type": "commit_offsets", "offsets": {"k3": 7}}, timeout=10)
        await c.rpc("n1", {"type": "commit_offsets", "offsets": {"k3": 4}}, timeout=10)
        return (await c.rpc("n1", {"type": "list_committed_offsets", "keys": ["k3"]}, timeout=10))["offsets"]

    assert run_virtual(main()).get("k3") == 7


@your_code(2, "under 3 messages per operation, p99 send under 100 ms in a burst")
def test_stage2_efficient():
    world = build_world("kafka_log", variant(), 1)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 5


def test_a_second_picture_shows_what_the_clients_see():
    from live.views import adapter_for, set_view, views_for

    world = build_world("kafka_log", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights
    text, colour = frame.state
    assert text and len(text) <= 13
