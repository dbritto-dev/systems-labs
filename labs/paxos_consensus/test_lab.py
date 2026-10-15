import asyncio
import functools
import itertools

import pytest

from core.contract import load
from core.net import Client, Network, ask
from core.testing import build_world, variant, your_code
from core.vtime import VirtualRun, run_virtual
from labs.paxos_consensus import reference as ref
from labs.paxos_consensus import scenario

code = load("paxos_consensus", variant(), scenario.NAMES)
AGREE, KEPT, LIVE, CHEAP = range(4)  # goal order in the World


# ------------------------------------------------------------- the stages, as people write them


class _FirstWins(ref.PaxosNode):
    """Stage 0, as given: each node keeps the first value it hears for a slot."""

    async def on_command(self, msg):
        value = msg.body["value"]
        self.waiting[value] = msg
        slot = self.free_slot()
        self.busy.add(slot)
        for node in self.node_ids:
            self.send(node, {"type": "propose", "slot": slot, "value": value})

    async def tick(self):
        return


class _Basic(ref.PaxosNode):
    """Stage 1: a full Paxos round (prepare, then accept) for every command, on whichever node it lands."""

    async def on_command(self, msg):
        self.waiting[msg.body["value"]] = msg
        self.spawn(self.submit(msg.body["value"]))

    async def tick(self):
        return


class _BasicNoAdopt(_Basic):
    """Stage 1 without its one rule: it proposes its own value even when a promise reports another."""

    async def paxos(self, slot, value):
        ballot = self.next_ballot(max(self.promised, self.highest))
        self.see(ballot)
        if len(self.count(await self.broadcast({"type": "prepare", "ballot": ballot, "slot": slot}))) < self.majority:
            return None
        body = {"type": "accept", "ballot": ballot, "slot": slot, "value": value}
        if len(self.count(await self.broadcast(body))) < self.majority:
            return None
        self.decide(slot, value)
        return value


def _elect(node, start):
    """A campaign's phase 1, shared by the stage 2 variants: the ok promises, or None if it lost."""

    async def run():
        ballot = node.next_ballot(max(node.promised, node.highest))
        node.see(ballot)
        node.role, node.ballot, node.leader_id = "candidate", ballot, None
        node.deadline = node.now() + node.timeout()
        oks = node.count(await node.broadcast({"type": "prepare", "ballot": ballot, "slot": start}))
        if node.role != "candidate" or len(oks) < node.majority or node.highest > ballot:
            if node.role == "candidate":
                node.role = "follower"
            return None
        node.role, node.leader_id = "leader", node.node_id
        return oks

    return run()


class _NoNoop(ref.PaxosNode):
    """Multi-Paxos that proposes again what the promises reported, but leaves the gaps empty."""

    async def campaign(self):
        start = self.first_undecided()
        oks = await _elect(self, start)
        if oks is None:
            return
        best = {}
        for r in oks:
            for slot, (b, v) in r["accepted"].items():
                if slot >= start and (slot not in best or b > best[slot][0]):
                    best[slot] = (b, v)
        self.next_slot = max(best, default=start - 1) + 1
        for slot, (_, v) in best.items():
            if slot not in self.decided:
                self.spawn(self.phase2(slot, v))


class _NoAdopt(ref.PaxosNode):
    """Multi-Paxos whose new leader ignores what the promises reported and starts at its first gap."""

    async def campaign(self):
        start = self.first_undecided()
        if await _elect(self, start) is not None:
            self.next_slot = start


class _NoBackoff(ref.PaxosNode):
    """Multi-Paxos that outbids at once: preempted, it stands again right away, never waiting."""

    campaigning = False

    def step_down(self):
        super().step_down()
        if not self.campaigning:
            self.spawn(self.campaign())

    async def campaign(self):
        if self.campaigning:
            return
        self.campaigning = True
        try:
            await super().campaign()
        finally:
            self.campaigning = False
        if self.role == "follower":
            self.spawn(self.campaign())


def module(name, cls):
    return type(name, (), {"PaxosNode": cls})


FIRST_WINS = module("FIRST_WINS", _FirstWins)
BASIC = module("BASIC", _Basic)
BASIC_NO_ADOPT = module("BASIC_NO_ADOPT", _BasicNoAdopt)
NO_NOOP = module("NO_NOOP", _NoNoop)
NO_ADOPT = module("NO_ADOPT", _NoAdopt)
NO_BACKOFF = module("NO_BACKOFF", _NoBackoff)


@functools.cache
def world_of(v, minutes=1, seed=1):
    return build_world("paxos_consensus", v, minutes, seed=seed)


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def first(world, v):
    return results(world, v)[0][1]


# ------------------------------------------------------------- given behaviour


def test_the_given_code_runs():
    world = world_of("main")
    assert world.stage_index("main") is not None
    assert world.runs["main"].total("ops", 60) > 400


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("v", [FIRST_WINS, BASIC_NO_ADOPT, NO_ADOPT], ids=lambda v: v.__name__)
def test_unsafe_code_is_stage_0(v, seed):
    world = world_of(v, seed=seed)
    assert world.stage_index(v) == 0, results(world, v)
    assert not first(world, v)[AGREE]


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("v", [BASIC, NO_NOOP], ids=lambda v: v.__name__)
def test_safe_but_slow_or_costly_code_is_stage_1(v, seed):
    world = world_of(v, seed=seed)
    assert world.stage_index(v) == 1, results(world, v)
    assert first(world, v)[AGREE] and first(world, v)[KEPT]


def test_each_goal_catches_its_mistake():
    # First proposal wins: nodes decide different commands, and answered ones vanish; it is cheap.
    assert first(world_of(FIRST_WINS), FIRST_WINS) == [False, False, True, True]
    # Paxos per slot: safe, but proposers duel and every command costs prepare and accept to all.
    basic = first(world_of(BASIC), BASIC)
    assert basic[AGREE] and basic[KEPT] and not basic[LIVE] and not basic[CHEAP]
    run = world_of(BASIC).runs[BASIC]
    assert run.total("phase1", 60) > run.total("phase2", 60) / 2  # a prepare round for every accept round
    # A leader that leaves the gap empty: the log stops applying there, nothing is answered again.
    assert first(world_of(NO_NOOP), NO_NOOP) == [True, True, False, True]
    # A leader that ignores the promises overwrites the slots the old leader got chosen.
    assert first(world_of(NO_ADOPT), NO_ADOPT)[AGREE] is False


def test_outbidding_at_once_duels_after_a_pause():
    res = results(world_of(NO_BACKOFF, 2), NO_BACKOFF)
    assert res[0][1] == [True] * 4  # a crash alone elects one leader
    duel = [r for kind, r in res if kind == "duel"]
    assert duel and not duel[0][LIVE]  # the paused leader wakes up and the two outbid each other


@pytest.mark.parametrize("seed", [1, 2, 4])
def test_reference_passes_every_goal_for_ten_minutes(seed):
    world = world_of("reference", 10, seed=seed)
    run = world.runs["reference"]
    res = results(world, "reference")
    assert len(res) >= 7 and len({i.kind for i in run.incidents}) >= 3
    assert all(all(r) for _, r in res), [x for x in res if not all(x[1])]
    assert world.stage_index("reference") == 2  # Multi-Paxos


def test_the_first_crash_leaves_a_gap_and_two_chosen_slots():
    sim = VirtualRun()
    s = scenario._Sim(ref, 1, 10.0)
    for coro in (s.setup(), s.traffic(), s.chaos(), s.checker()):
        sim.spawn(coro)
    try:
        sim.run_until(29.0)
        old = s.nodes[s.ids[s.victims[20.0][0]]]
        assert old.dead
        gap = old._lost_slot
        alive = [n for n in s.nodes.values() if not n.dead]
        # The gap was filled with a no-op, and the two chosen slots kept the old leader's values.
        assert all(n.decided[gap] == ref.NOOP for n in alive)
        sent = {slot for slot, _ in old._sent_next}
        assert sent == {gap + 1, gap + 2}
        for slot in sent:
            values = {n.accepted[slot][1] for n in alive if slot in n.accepted}
            assert len(values) == 1 and all(n.decided[slot] in values for n in alive)
        assert not s.events  # no disagreement
    finally:
        for node in s.nodes.values():
            node.kill()
        sim.close()


def test_incidents_are_random_but_the_first_is_fixed():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "proposer_crash") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"proposer_crash", "acceptor_crash", "lossy", "partition", "duel"}
    assert all(i.cause for i in later)


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = world_of("reference", 7)
    run = world.runs["reference"]
    assert run.keys["msgs"] == sorted(run.keys["msgs"]) and run.keys["ops"] == sorted(run.keys["ops"])
    assert run.keys["ops"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    assert run.total("ops", 1e9) == sum(len(p["tables"]["ops"]) for p in pieces)


# ------------------------------------------------------------- your code, piece by piece


def cluster(cls, body, latency=0.02):
    """Five nodes of `cls` on a network, and a client; run `body(net, nodes, client)` on virtual time."""

    async def main():
        net = Network(latency=latency, jitter=0.2, seed=1)
        ids = [f"n{i}" for i in range(5)]
        nodes = [cls(n, ids) for n in ids]
        for n in nodes:
            net.join(n)
        client = Client("c1")
        net.join(client)
        return await body(net, nodes, client)

    return run_virtual(main())


def leaders(nodes):
    return [n for n in nodes if n.role == "leader"]


@your_code(1, "on_prepare promises a higher ballot and reports what it accepted; refuses a lower one")
def test_stage1_prepare():
    async def body(net, nodes, client):
        node = nodes[0]
        node.promised, node.accepted[4] = 7, (7, 42)
        low = ask(node, {"type": "prepare", "ballot": 6, "slot": 3})
        high = ask(node, {"type": "prepare", "ballot": 12, "slot": 3})
        return low, high, node.promised

    low, high, promised = cluster(code.PaxosNode, body)
    assert low["ok"] is False and low["promised"] == 7
    assert high["ok"] is True and {int(k): list(v) for k, v in high["accepted"].items()} == {4: [7, 42]}
    assert promised == 12


@your_code(1, "on_accept accepts a ballot at least as high as its promise, and refuses a lower one")
def test_stage1_accept():
    async def body(net, nodes, client):
        node = nodes[0]
        node.promised = 7
        low = ask(node, {"type": "accept", "ballot": 6, "slot": 0, "value": 5})
        same = ask(node, {"type": "accept", "ballot": 7, "slot": 0, "value": 9})
        return low, same, tuple(node.accepted[0])

    low, same, accepted = cluster(code.PaxosNode, body)
    assert low["ok"] is False and same["ok"] is True and accepted == (7, 9)


@your_code(1, "paxos() proposes the value a promise reported, never its own over it")
def test_stage1_adopts_the_accepted_value():
    async def body(net, nodes, client):
        for n in nodes[1:3]:
            n.accepted[0] = (6, 42)  # maybe chosen by a proposer that died
        chosen = await nodes[0].paxos(0, 99)
        await asyncio.sleep(0.5)
        return chosen, [n.decided.get(0) for n in nodes]

    chosen, decided = cluster(code.PaxosNode, body)
    assert chosen == 42 and set(decided) == {42}


@your_code(1, "two proposers racing for one slot: every node decides the same value")
def test_stage1_racing_proposers_agree():
    async def body(net, nodes, client):
        a, b = await asyncio.gather(nodes[0].paxos(0, 1), nodes[3].paxos(0, 2))
        await asyncio.sleep(0.5)
        return a, b, [n.decided.get(0) for n in nodes]

    a, b, decided = cluster(code.PaxosNode, body)
    assert {a, b} - {None} <= set(decided) and len(set(decided) - {None}) == 1


@your_code(1, "the first incident: no slot decided two ways, nothing answered lost")
def test_stage1_safe_goals():
    res = first(world_of(variant()), variant())
    assert res[AGREE] and res[KEPT]


@your_code(2, "one leader is elected; the others follow it and redirect clients to it")
def test_stage2_one_leader():
    async def body(net, nodes, client):
        await asyncio.sleep(2.0)
        leader = leaders(nodes)
        reply = await client.rpc(next(n for n in nodes if n.role != "leader").node_id,
                                 {"type": "command", "value": 1}, timeout=1.0)
        return [n.node_id for n in leader], {n.leader_id for n in nodes if n.role != "leader"}, reply

    found, followed, reply = cluster(code.PaxosNode, body)
    assert len(found) == 1 and followed == set(found)
    assert reply["type"] == "command_redirect" and reply["leader"] == found[0]


@your_code(2, "a leader decides each command with one accept round: at most 16 messages a command")
def test_stage2_one_round_per_command():
    async def body(net, nodes, client):
        await asyncio.sleep(2.0)
        leader = leaders(nodes)[0].node_id
        before = len(net.log)
        for v in range(1, 41):
            reply = await client.rpc(leader, {"type": "command", "value": v}, timeout=1.0)
            assert reply["type"] == "command_ok"
        between = [d for d in net.log[before:] if d.src != d.dest and d.src != "c1" and d.dest != "c1"]
        await asyncio.sleep(0.5)
        return len(between), {d.type for d in between}, [len(n.decided) for n in nodes]

    sent, kinds, decided = cluster(code.PaxosNode, body)
    assert sent <= 16 * 40 and "prepare" not in kinds
    assert min(decided) >= 40


@your_code(2, "a new leader proposes again what was accepted, and fills the gap before it with a no-op")
def test_stage2_new_leader_fills_gaps():
    async def body(net, nodes, client):
        for n in nodes[1:4]:
            n.accepted[1] = (6, 77)  # chosen in slot 1 by a leader that died; slot 0 never reached anyone
        await asyncio.sleep(2.0)
        return [n.decided.get(0) for n in nodes], [n.decided.get(1) for n in nodes]

    gap, chosen = cluster(code.PaxosNode, body)
    assert set(gap) == {ref.NOOP} and set(chosen) == {77}


@your_code(2, "the first incident: every goal OK")
def test_stage2_every_goal():
    assert first(world_of(variant()), variant()) == [True] * 4
    assert world_of(variant()).stage_index(variant()) == 2


# ------------------------------------------------------------- the pictures


def test_two_pictures_cluster_first():
    from live.canvas import GREEN, MUTED, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v, t: float):
        world = world_of(v)
        assert views_for(world) == ["peers", "cluster", "lanes"] and world.view == "peers"  # peers opens first
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == 5
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        set_view(world, "peers")  # back to the one it opens with (world_of keeps the world)
        return frame, lanes

    calm, _ = picture("reference", 15.0)
    assert calm.nodes.count(GREEN) == 1 and RED not in calm.nodes  # one leader, marked green
    crashed, lanes = picture("reference", 21.5)
    assert MUTED in crashed.nodes and crashed.nodes.count(GREEN) == 1  # the old one down, a new one leads
    assert RED not in [c for c, _ in lanes.outcomes]
    split = next(e[0] for e in world_of(FIRST_WINS).runs[FIRST_WINS].rows("events", 0, 60))
    given, lanes = picture(FIRST_WINS, split + 0.1)
    assert RED in given.nodes and GREEN not in given.nodes  # no leader; a node that decided differently


def test_the_peers_picture_shows_the_leader_the_crash_and_a_split_decision():
    from live.canvas import GREEN, MUTED, RED
    from live.views import adapter_for, set_view

    def peers(v, t: float):
        world = world_of(v)
        assert type(world).view == "peers"
        set_view(world, "peers")
        return world, adapter_for(world).frame(v, t, 90)

    world, crashed = peers("reference", 21.5)  # the leader crashed mid-round: another one leads
    outlines = [p.outline for p in crashed.peers]
    assert outlines.count(GREEN) == 1 and MUTED in outlines and RED not in outlines
    i = outlines.index(GREEN)
    ballot = int(crashed.peers[i].label[0].rsplit("b", 1)[1])
    assert crashed.peers[i].label[0] == world.s("peer_leader", node=f"n{i}", ballot=ballot)  # "n3 leader b13"
    assert crashed.links  # and the messages it sends
    split = next(e[0] for e in world_of(FIRST_WINS).runs[FIRST_WINS].rows("events", 0, 60))
    world, given = peers(FIRST_WINS, split + 0.1)  # no ballots: two nodes decide one slot two ways
    outlines = [p.outline for p in given.peers]
    assert RED in outlines and GREEN not in outlines
    assert any(p.label[0] == world.s("peer_split", node=f"n{i}") for i, p in enumerate(given.peers))
