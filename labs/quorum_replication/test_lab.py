import asyncio
import functools
import itertools

from core.contract import load
from core.net import RPCError
from core.testing import build_world, variant, your_code
from labs.quorum_replication import reference as ref
from labs.quorum_replication import scenario

code = load("quorum_replication", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Quorums(ref.QuorumNode):  # stage 1: W=2, R=2, newest version wins; nothing repairs a replica
    async def replicate(self, replica, key, version, value):
        try:
            await self.rpc(replica, {"type": "store", "key": key, "version": version, "value": value}, timeout=0.5)
            return True
        except (TimeoutError, RPCError):
            return False

    async def read_repair(self, *args):
        return

    async def hand_off(self):
        return


class ReadRepairOnly(Quorums):  # repairs only the keys someone reads
    read_repair = ref.QuorumNode.read_repair


class WriteAll(Quorums):  # W=3, R=1: never stale, but one sick node fails a third of the writes
    async def on_put(self, msg):
        key, value = msg.body["key"], msg.body["value"]
        version = (self.now(), self.node_id)
        oks = await asyncio.gather(*(self.replicate(r, key, version, value)
                                     for r in ref.replicas_for(key, self.node_ids)))
        self.reply(msg, {"type": "put_ok"} if all(oks) else {"type": "error", "code": 11})

    async def on_get(self, msg):
        key = msg.body["key"]
        got = await self.fetch(ref.replicas_for(key, self.node_ids)[0], key)
        self.reply(msg, {"type": "get_ok", "value": got[2]} if got else {"type": "error", "code": 11})


class Chatty(ref.QuorumNode):  # repairs, but by pushing every key to its replicas every 2 s
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.every(2.0, self.push_all)

    async def push_all(self):
        for key, (version, value) in list(self.store.items()):
            for r in ref.replicas_for(key, self.node_ids):
                if r != self.node_id:
                    self.send(r, {"type": "store", "key": key, "version": version, "value": value})


def module(cls):
    return type(cls.__name__, (), {"QuorumNode": cls})


QUORUMS, READ_REPAIR, WRITE_ALL, CHATTY = map(module, (Quorums, ReadRepairOnly, WriteAll, Chatty))
STALE, ANSWERED, SYNC, MSGS = range(4)


@functools.cache
def world_of(v, minutes=1):
    return build_world("quorum_replication", v, minutes)


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_one_copy_reads_miss_the_latest_write():
    piece = scenario.run("main", chunk=0)
    gets = [o for o in piece["tables"]["ops"] if o[1] == scenario.GET and o[6]]
    assert gets and sum(o[7] for o in gets) > len(gets) / 10
    assert world_of("main").stage_index("main") == 0


def test_stage_variants_land_on_their_stage():
    # 0 one copy (or never stale but not available), 1 quorums, 2 quorums + repair
    for v, stage in ((WRITE_ALL, 0), (QUORUMS, 1), (READ_REPAIR, 1), (CHATTY, 1)):
        world = world_of(v)
        assert world.stage_index(v) == stage, (v.__name__, results(world, v))


def test_each_goal_catches_its_mistake():
    (kind, wa), = results(world_of(WRITE_ALL), WRITE_ALL)
    assert wa[STALE] and not wa[ANSWERED]
    (_, q), = results(world_of(QUORUMS), QUORUMS)
    assert q[STALE] and q[ANSWERED] and not q[SYNC] and q[MSGS]
    (_, ch), = results(world_of(CHATTY), CHATTY)
    assert ch[SYNC] and not ch[MSGS]


def test_without_repair_a_node_that_was_down_stays_behind():
    res = results(build_world("quorum_replication", QUORUMS, 4), QUORUMS)
    down = [r for kind, r in res if kind in ("crash", "isolate")]
    assert len(down) >= 2 and all(r[STALE] and not r[SYNC] for r in down)


def test_reference_passes_every_goal():
    world = build_world("quorum_replication", "reference", 4)
    res = results(world, "reference")
    assert len(res) >= 3 and all(all(r) for _, r in res)
    assert world.stage_index("reference") == 2


def test_incidents_are_random_but_the_first_crashes_n2_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "crash") for i in firsts)
    assert all(scenario.victim(i, s) == 2 for i, s in zip(firsts, (1, 2, 9)))
    later = list(itertools.islice(scenario.incidents(4), 30))
    assert {i.kind for i in later} == {"crash", "isolate", "slow"} and all(i.cause for i in later)
    assert len({scenario.victim(i, 4) for i in later}) == scenario.NODES


# ------------------------------------------------------------- your code


def first(v=None):
    v = v or variant()
    return [r.ok for r in world_of(v).runs[v].settled[0]]


@your_code(1, "quorums: no stale reads, every request answered with a node down")
def test_stage1_quorums():
    assert first()[:2] == [True, True]


@your_code(2, "replicas in sync 10 s after the node is back, under 10 messages per operation")
def test_stage2_repair():
    assert first() == [True] * 4


def test_a_second_picture_shows_what_the_clients_see():
    from live.canvas import RED
    from live.views import adapter_for, set_view, views_for

    world = build_world("quorum_replication", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights or frame.outcomes
    text, colour = frame.state
    assert text and len(text) <= 13
    assert RED not in [c for c, _ in frame.outcomes]  # no stale reads (red) even with a node down
