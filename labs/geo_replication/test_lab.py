import asyncio
import itertools

import pytest

from core.contract import load
from core.net import Client, RPCError
from core.testing import build_world, starting_code, variant, your_code
from core.vtime import now, run_virtual
from labs.geo_replication import reference as R
from labs.geo_replication import scenario
from labs.geo_replication.api import REGIONS, nearest

LAB = "geo_replication"
code = load(LAB, variant(), (*scenario.NAMES, "TIMEOUT", "HAND_OFF"))
READ_P99, WRITE_P99, RYW, AVAILABLE, AT_RISK = range(5)  # the goals, in lab.stage_of's order


class Replicas(R.RegionNode):  # stage 1: a replica in every region; writes at the primary, shipped in batches
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.every(R.SHIP_EVERY, self.batch)

    async def hand_off(self):
        pass

    async def on_read(self, msg):
        version, value = self.store.get(msg.body["key"], (0, None))
        self.reply(msg, {"type": "read_ok", "value": value, "version": version})

    async def on_write(self, msg):
        if self.node_id != R.PRIMARY:
            await self.forward(msg, R.PRIMARY)
            return
        key, value = msg.body["key"], msg.body["value"]
        version = self.now()
        self.keep(key, version, value)
        self.log.append((key, version, value))
        self.reply(msg, {"type": "write_ok", "version": version})

    async def batch(self):
        if self.log:
            for r in nearest(self.node_id):
                self.send(r, {"type": "replicate", "items": list(self.log)})
            self.log.clear()


class Async(R.RegionNode):  # every region takes writes, but acknowledges at once and replicates after
    async def on_write(self, msg):
        key, value = msg.body["key"], msg.body["value"]
        version = max(self.now(), msg.body.get("token", 0) + 1e-6)
        self.keep(key, version, value)
        self.reply(msg, {"type": "write_ok", "version": version})
        await self.replicate(key, version, value)


class WaitAll(R.RegionNode):  # acknowledges a write only once every region has it
    async def replicate(self, key, version, value):
        tasks = [asyncio.ensure_future(self.send_to(r, key, version, value)) for r in nearest(self.node_id)]
        return all(await asyncio.gather(*tasks))


class NoToken(R.RegionNode):  # stage 1 too: two copies per write, but reads ignore the session token
    async def on_read(self, msg):
        version, value = self.store.get(msg.body["key"], (0, None))
        self.reply(msg, {"type": "read_ok", "value": value, "version": version})


class Buggy(R.RegionNode):
    async def on_read(self, msg):
        raise ValueError("a bug in on_read")


class NoStore(R.RegionNode):
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        del self.store


def as_module(cls):
    return type(cls.__name__.upper(), (), {"RegionNode": cls})


REPLICAS, ASYNC, WAIT_ALL, NO_TOKEN = (as_module(c) for c in (Replicas, Async, WaitAll, NoToken))


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled) if all(r is not None for r in run.settled[i])]


def by_kind(world, v) -> dict[str, list[list[bool]]]:
    out: dict[str, list[list[bool]]] = {}
    for inc, result in zip(world.runs[v].incidents, statuses(world, v)):
        out.setdefault(inc.kind, []).append(result)
    return out


# ------------------------------------------------------------- given behaviour


def test_the_first_incident_cuts_us_off_at_0_20():
    for seed in (1, 2, 99):
        first = next(scenario.incidents(seed))
        assert (first.t0, first.t1, first.kind) == (20.0, 32.0, "partition")
        assert scenario.victim(first, seed) == 0  # us, the primary of stages 0 and 1
    incs = list(itertools.islice(scenario.incidents(3), 40))
    assert {i.kind for i in incs} == {"down", "partition", "slow", "peak"} and all(i.cause for i in incs)
    gaps = [b.t0 - a.t1 for a, b in zip(incs, incs[1:])]
    assert min(gaps) >= scenario.QUIET  # each incident is judged before the next one starts
    assert {scenario.victim(i, 3) for i in incs[1:]} == {0, 1, 2}


def test_the_network_has_oceans_in_it():
    assert nearest("us") == ["eu", "ap"] and nearest("eu") == ["us", "ap"] and nearest("ap") == ["us", "eu"]
    piece = scenario.run("reference", chunk=0)
    msgs = [m for m in piece["tables"]["msgs"] if m[3] is not None and m[0] < 19]
    one_way = {}
    for sent, a, b, arrived, _ in msgs:
        one_way.setdefault(frozenset((a, b)), []).append(arrived - sent)
    us_eu, us_ap, eu_ap = (one_way[frozenset(p)] for p in ((0, 1), (0, 2), (1, 2)))
    assert 0.055 <= min(us_eu) and max(us_eu) <= 0.085
    assert 0.08 <= min(us_ap) and max(us_ap) <= 0.12
    assert 0.12 <= min(eu_ap) and max(eu_ap) <= 0.18


@starting_code
def test_one_primary_region_is_slow_far_away_and_keeps_one_copy():
    for seed in (1, 2, 3):
        world = build_world(LAB, "main", 1, seed=seed)
        assert statuses(world, "main")[0] == [False, False, True, True, False]  # the apps retry in us
        assert world.stage_index("main") == 0  # One primary region


def test_read_replicas_read_fast_but_users_miss_their_writes():
    for seed in (1, 2, 3):
        world = build_world(LAB, REPLICAS, 1, seed=seed)
        assert statuses(world, REPLICAS)[0] == [True, False, False, True, False]
        assert world.stage_index(REPLICAS) == 1  # Read replicas


def test_acknowledging_before_a_second_copy_leaves_writes_at_risk():
    for seed in (1, 2, 3):
        world = build_world(LAB, ASYNC, 1, seed=seed)
        assert statuses(world, ASYNC)[0] == [True, True, True, True, False]
        assert world.stage_index(ASYNC) == 1  # fast everywhere, but a region lost takes writes with it


def test_waiting_for_every_region_stops_writes_when_one_is_cut_off():
    for seed in (1, 2, 3):
        world = build_world(LAB, WAIT_ALL, 1, seed=seed)
        result = statuses(world, WAIT_ALL)[0]
        assert result[READ_P99] and not result[WRITE_P99] and not result[AVAILABLE] and result[AT_RISK]
        assert world.stage_index(WAIT_ALL) == 1


def test_without_session_tokens_a_cut_off_region_shows_users_old_data():
    for seed in (1, 2, 3):
        world = build_world(LAB, NO_TOKEN, 1, seed=seed)
        assert statuses(world, NO_TOKEN)[0] == [True, True, False, True, True]
        assert world.stage_index(NO_TOKEN) == 1  # the first incident catches it
    missed = 0
    for seed in (1, 5):
        world = build_world(LAB, NO_TOKEN, 10, seed=seed)
        cut = by_kind(world, NO_TOKEN)["partition"]
        assert cut and all(not r[RYW] for r in cut)  # they wrote elsewhere, then read at home
        missed += len(cut)
        assert all(r[READ_P99] and r[AVAILABLE] and r[AT_RISK] for rs in by_kind(world, NO_TOKEN).values() for r in rs)
    assert missed >= 4


def test_reference_passes_every_goal_for_ten_minutes():
    kinds = set()
    for seed in (1, 3, 5):
        world = build_world(LAB, "reference", 10, seed=seed)
        results = statuses(world, "reference")
        assert len(results) >= 6 and all(all(r) for r in results), results
        kinds |= {i.kind for i in world.runs["reference"].incidents}
        assert world.stage_index("reference") == 2  # Writes in every region
    assert kinds == {"down", "partition", "slow", "peak"}


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world(LAB, "reference", 7)
    run = world.runs["reference"]
    assert run.keys["ops"] == sorted(run.keys["ops"]) and run.keys["ops"][0] >= 60  # minute 0 is gone
    pieces = list(itertools.islice(scenario.stream("reference"), 7))
    assert run.total("ops", 1e9) == sum(len(p["tables"]["ops"]) for p in pieces)
    assert world.stage_index("reference") == 2  # still judged once the first incident's rows are gone


def test_the_events_name_the_region():
    world = build_world(LAB, "main", 1)
    start = next(e for e in world.runs["main"].timeline if e.kind == "start")
    assert "us" in start.text and world.text.CAUSES["fiber_cut"] in start.text


def test_a_bug_in_your_node_is_reported():
    with pytest.raises(ValueError, match="on_read"):
        scenario.run(as_module(Buggy), chunk=0)
    with pytest.raises(AttributeError, match="self.store"):
        scenario.run(as_module(NoStore), chunk=0)


@starting_code
def test_three_pictures_the_peers_first():
    from live.canvas import EXTRA2, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    worlds = {v: build_world(LAB, v, 1) for v in ("main", "reference")}
    assert views_for(worlds["main"]) == ["peers", "cluster", "lanes"] and worlds["main"].view == "peers"

    def pictures(v: str, t: float):
        world = worlds[v]
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == 9
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert frame.state[0] in text
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        assert len(lanes.state[0]) <= 13
        assert lanes.state[0] in "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        return frame, lanes

    for v in ("main", "reference"):
        frame, lanes = pictures(v, 25.0)  # us is cut off: fenced, not down
        assert frame.groups == [1, 0, 0] * 3 and RED not in frame.nodes
        assert lanes.state[0] == worlds[v].s("lanes_cut", name="us")
    frame, lanes = pictures("main", 25.0)
    assert frame.drops  # requests forwarded to us die half way
    frame, lanes = pictures("main", 45.0)
    assert any(c == EXTRA2 for _, _, _, c in frame.flights)  # requests forwarded across an ocean
    frame, lanes = pictures("reference", 25.0)
    assert not any(c == RED for c, _ in lanes.outcomes)  # nothing fails: us's users write in eu


@starting_code
def test_the_peers_picture_shows_the_oceans_and_the_region_cut_off():
    from live.canvas import BLUE, EXTRA2, RED, WHITE, plain
    from live.frame import compose
    from live.views import adapter_for

    def peers(v, times):
        world = build_world(LAB, v, 1)
        assert world.view == "peers"
        return world, [adapter_for(world).frame(v, t, 90) for t in times]

    calm = [k / 2 for k in range(10, 38)]  # 0:05 to 0:19
    for v in ("main", "reference"):
        world, (cut,) = peers(v, [25.0])
        assert [p.short for p in cut.peers] == ["us", "eu", "ap"]
        assert set(cut.link_labels.values()) == {"70ms", "100ms", "150ms"}
        assert cut.groups == [1, 0, 0] and cut.peers[0].label == (world.s("peer_cut", name="us"), RED)
        assert cut.peers[0].outline != RED  # cut off, not down
        text = "\n".join(plain(line) for line in compose(world, v, 25.0, 110, 44))
        assert "✕" in text and "150ms" in text  # us's two oceans cut; eu–ap still there
    world, given = peers("main", calm)
    _, solved = peers("reference", calm)
    behind = [p for f in given[4:] for p in f.peers[1:]]  # one primary in us: eu and ap lag behind it
    assert behind and all("−" in p.label[0] and p.outline != BLUE for p in behind)
    assert any(c == EXTRA2 for f in given for _, _, c in f.links)  # writes forwarded across an ocean
    assert all(p.outline == BLUE and p.label[0] == p.short for f in solved for p in f.peers)
    assert all(c == BLUE for f in solved for *_, c in f.links)  # every region writes locally: only replication
    assert max(f.peers[0].fill for f in given) > 0.6 > max(p.fill for f in solved for p in f.peers)  # us busiest
    _, during = peers("reference", [k / 2 for k in range(42, 58)])  # 0:21 to 0:29: us's users moved
    moved = {c for f in during for a, b, _, c in f.flights if a == -1 and b != 0}
    assert {WHITE, EXTRA2} <= moved  # home users in eu and ap, and us's users failed over to them


# ------------------------------------------------------------- your code: three regions, one user


def regions(script, cls=None, user_region: int = 1):
    """Run `script(net, nodes, app)` on a network of the three regions and a user's app in one of them."""

    async def main():
        net = scenario._Net(seed=1)
        nodes = []
        for i, r in enumerate(REGIONS):
            node = (cls or code.RegionNode)(r, list(REGIONS))
            net.join(node)
            net.where[r] = i
            nodes.append(node)
        app = Client("app")
        net.join(app)
        net.where["app"] = user_region
        result = await script(net, nodes, app)
        if net.bugs:
            raise net.bugs[0]
        return result

    return run_virtual(main())


async def ask(app, region: str, body: dict, timeout: float = 1.0):
    """(reply or None, seconds it took)."""
    t = now()
    try:
        reply = await app.rpc(region, body, timeout=timeout)
    except (TimeoutError, RPCError):
        reply = None
    return reply, now() - t


@your_code(1, "every region answers reads from its own copy, and the primary ships its writes")
def test_stage1_local_reads():
    async def script(net, nodes, app):
        wrote, _ = await ask(app, "eu", {"type": "write", "key": "u7", "value": 5, "token": 0})
        await asyncio.sleep(0.5)
        read, took = await ask(app, "eu", {"type": "read", "key": "u7", "token": 0})
        return wrote, read, took, [n.store.get("u7") for n in nodes]

    wrote, read, took, stores = regions(script)
    assert wrote and wrote["type"] == "write_ok"
    assert read and read["value"] == 5 and took < 0.02  # answered in eu, not across the Atlantic
    assert all(s is not None and s[1] == 5 for s in stores)  # every region has a copy


@your_code(1, "the first incident: reads stay fast in every region")
def test_stage1_first_incident():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0][READ_P99] and world.stage_index(variant()) >= 1


@your_code(2, "a write is acknowledged once a second region holds it, one ocean away")
def test_stage2_two_copies():
    async def script(net, nodes, app):
        reply, took = await ask(app, "eu", {"type": "write", "key": "u300", "value": 9, "token": 0})
        held = [n.store.get("u300") is not None for n in nodes]
        return reply, took, held

    reply, took, held = regions(script)
    assert reply and reply["type"] == "write_ok"
    assert sum(held) >= 2  # when the user hears "saved", two regions have it
    assert 0.1 < took < 0.25  # eu waited for us (~140 ms), not for ap (~300 ms)


@your_code(2, "a write still succeeds with one other region down; a cut-off region refuses it")
def test_stage2_one_region_down():
    async def script(net, nodes, app):
        net.down.add(0)  # us is down
        ok, took = await ask(app, "eu", {"type": "write", "key": "u301", "value": 1, "token": 0})
        net.down.clear()
        net.cut_off.add(1)  # eu cannot reach the others
        refused, _ = await ask(app, "eu", {"type": "write", "key": "u301", "value": 2, "token": 0})
        return ok, took, refused

    ok, took, refused = regions(script)
    assert ok and ok["type"] == "write_ok" and took < 0.5  # with ap's copy
    assert refused is None  # one copy only: an error, so the app retries elsewhere


@your_code(2, "a region whose copy is older than the session token fetches the newer one")
def test_stage2_session_token():
    async def script(net, nodes, app):
        nodes[0].store["u5"] = (10.0, 42)  # only us has the user's latest write
        nodes[1].store["u5"] = (4.0, 7)
        newer, _ = await ask(app, "eu", {"type": "read", "key": "u5", "token": 10.0})
        older, took = await ask(app, "eu", {"type": "read", "key": "u5", "token": 0})
        return newer, older, took, nodes[1].store["u5"]

    newer, older, took, kept = regions(script)
    assert newer and newer["value"] == 42  # never older than what the user wrote
    assert kept[1] == 42  # and eu keeps it
    assert older and older["value"] == 42 and took < 0.02  # now answered at home


@your_code(2, "a region that was down catches up from hints")
def test_stage2_hints():
    async def script(net, nodes, app):
        net.down.add(0)
        await ask(app, "eu", {"type": "write", "key": "u302", "value": 3, "token": 0})
        missed = nodes[0].store.get("u302")
        net.down.clear()
        await asyncio.sleep(2 * code.HAND_OFF + 1.0)
        return missed, nodes[0].store.get("u302")

    missed, caught_up = regions(script)
    assert missed is None and caught_up is not None and caught_up[1] == 3


@your_code(2, "every goal passes on the first incident: us down")
def test_stage2_first_incident_every_goal():
    world = build_world(LAB, variant(), 1)
    assert statuses(world, variant())[0] == [True] * 5
    assert world.stage_index(variant()) == 2


def test_session_tokens_answer_like_a_dict_and_never_grow():
    tokens = scenario._Tokens(600, 600)
    size = len(tokens._floats)
    assert tokens.get((3, "u7"), 0) == 0
    tokens[(3, "u7")] = 12.5
    tokens[(3, "u8")] = 0
    tokens[(4, "u7")] = 7  # another code's integer versions come back as they went in
    tokens[(5, "x")] = 2.0  # a key the table has no room for
    assert tokens.get((3, "u7"), 0) == 12.5 and type(tokens.get((3, "u8"), 0)) is int
    assert tokens.get((4, "u7"), 0) == 7 and type(tokens.get((4, "u7"), 0)) is int
    assert tokens.get((5, "x"), 0) == 2.0 and tokens.get((599, "u599"), 0) == 0
    tokens[(4, "u7")] = 9.0
    assert tokens.get((4, "u7"), 0) == 9.0 and len(tokens._floats) == size
