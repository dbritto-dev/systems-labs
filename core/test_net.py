import asyncio

import pytest

from core.net import KV, Client, KVService, Network, Node, RPCError, Topology, ask
from core.vtime import run_virtual


class Echo(Node):
    async def on_echo(self, msg):
        self.reply(msg, {"type": "echo_ok", "echo": msg.body["echo"]})


class Store(Node):
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.seen = set()

    async def on_read(self, msg):
        self.reply(msg, {"type": "read_ok", "messages": sorted(self.seen)})


def cluster(n=3, cls=Echo, latency=0.1):
    net = Network(latency=latency, jitter=0.0)
    ids = [f"n{i}" for i in range(n)]
    nodes = [cls(i, ids) for i in ids]
    for node in nodes:
        net.join(node)
    client = Client("c1")
    net.join(client)
    return net, nodes, client


def test_rpc_takes_a_round_trip_of_latency():
    async def main():
        net, nodes, c = cluster()
        t0 = asyncio.get_running_loop().time()
        reply = await c.rpc("n1", {"type": "echo", "echo": "hi"})
        return reply, asyncio.get_running_loop().time() - t0, len(net.log)

    reply, took, sent = run_virtual(main())
    assert reply["echo"] == "hi" and reply["in_reply_to"] == 1
    assert took == pytest.approx(0.2) and sent == 2


def test_partitions_drop_messages_between_groups_only():
    async def main():
        net, nodes, c = cluster()
        net.partition([{"n0"}, {"n1", "n2"}])
        with pytest.raises(TimeoutError):
            await nodes[0].rpc("n1", {"type": "echo", "echo": 1}, timeout=0.5)
        ok = await nodes[1].rpc("n2", {"type": "echo", "echo": 2})
        reach = await c.rpc("n0", {"type": "echo", "echo": 3})  # clients reach everyone
        net.heal()
        back = await nodes[0].rpc("n1", {"type": "echo", "echo": 4})
        return ok["echo"], reach["echo"], back["echo"], [d.dropped for d in net.log]

    ok, reach, back, dropped = run_virtual(main())
    assert (ok, reach, back) == (2, 3, 4) and dropped.count(True) == 1


def test_unknown_message_types_get_an_error():
    async def main():
        net, nodes, c = cluster()
        with pytest.raises(RPCError) as err:
            await c.rpc("n0", {"type": "nope"})
        return err.value.code

    assert run_virtual(main()) == 10


def test_kv_cas_and_errors():
    async def main():
        net, nodes, c = cluster()
        net.join(KVService("lin-kv"))
        kv = KV(nodes[0], "lin-kv")
        with pytest.raises(RPCError) as missing:
            await kv.read("x")
        await kv.cas("x", None, 1, create=True)
        with pytest.raises(RPCError) as stale:
            await kv.cas("x", 0, 2)
        await kv.cas("x", 1, 2)
        return missing.value.code, stale.value.code, await kv.read("x")

    assert run_virtual(main()) == (20, 22, 2)


def test_seq_kv_may_return_an_older_value_but_never_go_back_for_a_client():
    async def main():
        net, nodes, c = cluster()
        net.join(KVService("seq-kv", stale=5.0, seed=3))
        writer, reader = KV(nodes[0]), KV(nodes[1])
        seen = []
        for v in range(1, 30):
            await writer.write("k", v)
            await asyncio.sleep(0.5)
            seen.append(await reader.read("k"))
        return seen

    seen = run_virtual(main())
    assert seen == sorted(seen) and seen[-1] < 29  # monotonic for a client, but stale


def test_ask_reads_a_node_without_the_network():
    async def main():
        net, nodes, c = cluster(cls=Store)
        nodes[0].seen = {3, 1}
        return ask(nodes[0], {"type": "read"}), len(net.log)

    reply, sent = run_virtual(main())
    assert reply["messages"] == [1, 3] and sent == 0


def test_grid_topology():
    t = Topology.grid([f"n{i}" for i in range(9)])
    assert sorted(t.neighbours["n4"]) == ["n1", "n3", "n5", "n7"]
    assert sorted(t.neighbours["n0"]) == ["n1", "n3"]


def test_a_periodic_task_that_awaits_stops_when_the_run_is_closed():
    from core.vtime import VirtualRun

    class Ticker(Node):
        def __init__(self, node_id, node_ids):
            super().__init__(node_id, node_ids)
            self.ticks = 0
            self.every(0.1, self.tick)

        async def tick(self):
            self.ticks += 1
            await self.sleep(0.05)  # awaits inside every(): cancellation must still get through

    async def boot():
        net = Network()
        net.join(Ticker("n0", ["n0"]))

    sim = VirtualRun()
    sim.spawn(boot())
    sim.run_until(1.0)
    sim.close()  # used to hang forever
    assert sim.loop.is_closed()
