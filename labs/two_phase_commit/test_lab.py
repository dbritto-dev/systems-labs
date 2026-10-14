import asyncio
import functools
import itertools

import pytest

from core.contract import load
from core.net import Client, Network, Node
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import run_virtual
from labs.two_phase_commit import reference as ref
from labs.two_phase_commit import scenario
from labs.two_phase_commit.api import DecisionLog, Life, ShardDB

code = load("two_phase_commit", variant(), scenario.NAMES)
BASELINE, ROLLED, PARTIAL, MONEY, DOUBT, COMPLETED = range(6)


# ------------------------------------------------------------- the stages, as people write them


class TwoPhase(ref.Coordinator):  # stage 1: decisions in memory, each sent once
    async def two_phase(self, txn, writes):
        votes = await asyncio.gather(*(self.vote(s, txn, a, d) for s, (a, d) in writes.items()))
        decision = "commit" if all(votes) else "abort"
        await self.finish(txn, decision, list(writes))
        return decision == "commit"

    async def finish(self, txn, decision, shards):
        for s in shards:
            self.send(s, {"type": decision, "txn": txn})

    async def recover(self):
        return


class WaitingShard(ref.Shard):  # stage 1: a shard in doubt just waits
    async def recover(self):
        return


class AloneShard(ref.Shard):  # gives up waiting after a second and aborts on its own
    async def recover(self):
        self.every(0.5, self.alone)

    async def alone(self):
        for txn, since in self.db.in_doubt().items():
            if self.now() - since >= 1.0:
                self.db.abort(txn)


class MemoryOnly(ref.Coordinator):  # resends and answers questions, but from memory: a crash forgets
    def __init__(self, node_id, node_ids, log):
        super().__init__(node_id, node_ids, log)
        self.decided = {}

    async def two_phase(self, txn, writes):
        self.active.add(txn)
        votes = await asyncio.gather(*(self.vote(s, txn, a, d) for s, (a, d) in writes.items()))
        decision = "commit" if all(votes) else "abort"
        self.decided[txn] = decision
        self.active.discard(txn)
        self.spawn(self.finish(txn, decision, list(writes)))
        return decision == "commit"

    async def finish(self, txn, decision, shards):
        await asyncio.gather(*(self.deliver(s, txn, decision) for s in shards))

    async def on_status(self, msg):
        txn = msg.body["txn"]
        d = self.decided.get(txn) or (None if txn in self.active else "abort")
        self.reply(msg, {"type": "status_ok", "decision": d})


class SendThenLog(ref.Coordinator):  # logs the commit, but after sending it
    async def two_phase(self, txn, writes):
        self.active.add(txn)
        votes = await asyncio.gather(*(self.vote(s, txn, a, d) for s, (a, d) in writes.items()))
        decision = "commit" if all(votes) else "abort"
        self.active.discard(txn)
        for s in writes:
            self.send(s, {"type": decision, "txn": txn})
        if decision == "commit":
            await self.log.write(txn, decision, list(writes))
        self.spawn(self.finish(txn, decision, list(writes)))
        return decision == "commit"


def module(name, coordinator, shard):
    return type(name, (), {"Coordinator": coordinator, "Shard": shard})


TWO_PC = module("TWO_PC", TwoPhase, WaitingShard)
ALONE = module("ALONE", TwoPhase, AloneShard)
MEMORY_ONLY = module("MEMORY_ONLY", MemoryOnly, ref.Shard)
SEND_THEN_LOG = module("SEND_THEN_LOG", SendThenLog, ref.Shard)


@functools.cache
def world_of(v, minutes=1, seed=1):
    return build_world("two_phase_commit", v, minutes, seed=seed)


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@starting_code
def test_one_shard_at_a_time_leaves_partial_commits():
    world = world_of("main")
    (kind, first), = results(world, "main")
    # n2 says no after n1 already wrote: partial commits, money created or destroyed
    assert first == [True, False, False, False, True, True]
    assert world.stage_index("main") == 0  # One shard at a time


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("v", [TWO_PC, ALONE, MEMORY_ONLY, SEND_THEN_LOG], ids=lambda v: v.__name__)
def test_two_phase_commit_without_full_recovery_is_stage_1(v, seed):
    world = world_of(v, seed=seed)
    assert world.stage_index(v) == 1, results(world, v)
    first = results(world, v)[0][1]
    assert first[ROLLED]  # no votes abort on every shard


def test_each_goal_catches_its_mistake():
    (_, two_pc), = results(world_of(TWO_PC), TWO_PC)
    # Nothing partial, but the crash leaves shards in doubt forever: money missing, rows locked.
    assert two_pc[PARTIAL] and not two_pc[MONEY] and not two_pc[DOUBT] and not two_pc[COMPLETED]
    for v in (ALONE, MEMORY_ONLY, SEND_THEN_LOG):
        (_, res), = results(world_of(v), v)
        # Resolved fast, but wrongly: the commit reached n1, the others aborted.
        assert not res[PARTIAL] and not res[MONEY] and res[DOUBT] and res[COMPLETED], v.__name__


def test_without_recovery_locked_rows_pile_up():
    res = results(world_of(TWO_PC, 4, seed=4), TWO_PC)
    assert len(res) >= 4
    assert all(not r[COMPLETED] for _, r in res)  # rows left locked in doubt block later transfers
    assert not res[-1][1][BASELINE]


def test_a_shard_that_decides_alone_breaks_atomicity_when_it_crashes():
    res = results(world_of(ALONE, 6, seed=4), ALONE)
    crashes = [r for kind, r in res if kind == "shard_crash"]
    assert crashes and not all(r[PARTIAL] for r in crashes)


@pytest.mark.parametrize("seed", [1, 4, 9])
def test_reference_passes_every_goal_for_ten_minutes(seed):
    world = world_of("reference", 10, seed=seed)
    run = world.runs["reference"]
    res = results(world, "reference")
    assert len(res) >= 8 and len({i.kind for i in run.incidents}) >= 4
    assert all(all(r) for _, r in res), [x for x in res if not all(x[1])]
    assert world.stage_index("reference") == 2  # 2PC with recovery


@starting_code
def test_the_reference_conserves_money_and_the_given_code_does_not():
    def drift(v):
        piece = next(itertools.islice(scenario.stream(v), 0, None))
        return piece["tables"]["state"][-1][-1]  # the checker's last look: money created or destroyed

    assert drift("reference") == 0
    assert drift("main") != 0


def test_incidents_are_random_but_the_first_is_fixed():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "overload") for i in firsts)
    assert all(scenario.victim(i, s) == 2 for i, s in zip(firsts, (1, 2, 9)))
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"overload", "refuse", "shard_crash", "coord_crash", "partition"}
    assert all(i.cause for i in later)


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = world_of("reference", 7)
    run = world.runs["reference"]
    assert run.keys["txns"] == sorted(run.keys["txns"])
    assert run.keys["txns"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    assert run.total("txns", 1e9) == sum(len(p["tables"]["txns"]) for p in pieces)


# ------------------------------------------------------------- your code, piece by piece

BALANCES = {"c1": 1000, "m1": 0, "f1": 0}
WRITES = {"n1": ["c1", -100], "n2": ["m1", 98], "n3": ["f1", 2]}


class Silent(Node):
    """A coordinator that is down: it hears nothing and answers nothing."""

    def __init__(self, node_id, node_ids, log):
        super().__init__(node_id, node_ids)

    async def recover(self):
        return

    def _deliver(self, msg):
        return


class Cluster:
    """A coordinator, three shards and a client on a small network, outside the scenario."""

    def __init__(self, mod=None) -> None:
        self.mod = mod or code
        self.net = Network(latency=0.03, jitter=0.0, seed=1)
        self.ids = ["n0", "n1", "n2", "n3"]
        self.dbs = [ShardDB(i, BALANCES) for i in range(3)]
        self.log = DecisionLog()
        self.client = Client("c1")
        self.net.join(self.client)
        self.nodes = {}

    def boot(self, node_id, cls=None) -> None:
        if node_id == "n0":
            node = (cls or self.mod.Coordinator)("n0", self.ids, self.log.view(Life()))
        else:
            node = (cls or self.mod.Shard)(node_id, self.ids, self.dbs[int(node_id[1]) - 1].view(Life()))
        self.net.join(node)
        self.nodes[node_id] = node
        node.spawn(node.recover())

    async def transfer(self, txn="t1"):
        reply = await self.client.rpc("n0", {"type": "transfer", "txn": txn, "writes": WRITES}, timeout=3.0)
        await asyncio.sleep(1.0)  # let the decision reach every shard
        return reply.get("committed")

    def balances(self):
        return [db.balance(a) for db, (a, _) in zip(self.dbs, WRITES.values())]

    def locked(self):
        return sum(len(db.locks) for db in self.dbs)


@your_code(1, "every shard votes yes: the transfer commits on all three, and the locks go")
def test_stage1_commit_everywhere():
    async def main():
        c = Cluster()
        for n in c.ids:
            c.boot(n)
        committed = await c.transfer()
        prepared = all(db.outcome.get("t1") == "commit" for db in c.dbs)  # prepared, then committed
        return committed, prepared, c.balances(), c.locked()

    assert run_virtual(main()) == (True, True, [900, 98, 2], 0)


@your_code(1, "one shard votes no: nothing is applied anywhere, and no row stays locked")
def test_stage1_abort_everywhere():
    async def main():
        c = Cluster()
        c.dbs[1].refuse = lambda txn: 0.0  # n2 says no (a constraint)
        for n in c.ids:
            c.boot(n)
        return await c.transfer(), c.balances(), c.locked()

    assert run_virtual(main()) == (False, [1000, 0, 0], 0)


async def _prepared_everywhere(c, txn="t7"):
    for db, (account, delta) in zip(c.dbs, WRITES.values()):
        assert await db.prepare(txn, account, delta)


@your_code(2, "a restarted coordinator sends again the commit its log holds")
def test_stage2_recover_resends_logged_commits():
    async def main():
        c = Cluster()
        await _prepared_everywhere(c)
        c.log.data["t7"] = ("commit", list(WRITES))  # it logged commit, then crashed before sending
        for n in c.ids:
            c.boot(n)
        await asyncio.sleep(3.0)
        return c.balances(), c.locked()

    assert run_virtual(main()) == ([900, 98, 2], 0)


@your_code(2, "a shard in doubt asks; a transfer the log never saw is aborted (presumed abort)")
def test_stage2_presumed_abort():
    async def main():
        c = Cluster()
        await _prepared_everywhere(c)  # the coordinator died collecting votes: nothing logged
        for n in c.ids:
            c.boot(n)
        await asyncio.sleep(3.0)
        return c.balances(), c.locked()

    assert run_virtual(main()) == ([1000, 0, 0], 0)


@your_code(2, "while the coordinator is down, a shard in doubt keeps waiting: it never decides alone")
def test_stage2_never_decide_alone():
    async def main():
        c = Cluster()
        await _prepared_everywhere(c)
        c.log.data["t7"] = ("commit", list(WRITES))
        c.boot("n0", Silent)
        for n in ("n1", "n2", "n3"):
            c.boot(n)
        await asyncio.sleep(5.0)
        waiting = (c.balances(), c.locked())
        c.boot("n0")  # it is back
        await asyncio.sleep(3.0)
        return waiting, (c.balances(), c.locked())

    waiting, after = run_virtual(main())
    assert waiting == ([1000, 0, 0], 3)  # in doubt: the rows stay locked
    assert after == ([900, 98, 2], 0)


@your_code(2, "the first incident: nothing partial, nothing left in doubt, every goal OK")
def test_stage2_first_incident_every_goal():
    (_, first), = results(world_of(variant()), variant())
    assert first == [True] * 6


# ------------------------------------------------------------- the pictures


@starting_code
def test_two_pictures_cluster_first():
    from live.canvas import EXTRA2, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v, t: float):
        world = world_of(v)
        set_view(world, "cluster")
        assert views_for(world) == ["cluster", "lanes"] and world.view == "cluster"  # cluster opens first
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == 4
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        set_view(world, "cluster")
        return frame, lanes

    down, lanes = picture("main", 27.0)  # the coordinator was OOM-killed at 0:26
    assert down.nodes[0] == RED and lanes.closed
    given, _ = picture("main", 23.0)
    assert RED in given.nodes[1:]  # n2 said no after another shard wrote: a partial commit
    doubt, _ = picture("reference", 27.5)
    assert EXTRA2 in doubt.nodes[1:] and RED not in doubt.nodes[1:]  # in doubt (orange), never partial
    healed, _ = picture("reference", 31.0)
    assert healed.nodes == [healed.nodes[0]] * 4 and healed.nodes[0] not in (RED, EXTRA2)
