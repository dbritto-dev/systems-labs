import asyncio
import itertools

from core.contract import load
from core.net import Client, Network, ask
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.raft_consensus import reference as ref
from labs.raft_consensus import scenario

code = load("raft_consensus", variant(), scenario.NAMES)
LEADER_OK, ELECTION_OK, COMMITTED_OK, SAFE_OK, AVAILABLE_OK = range(5)  # goal order in the World


class _AcksAlone(ref.RaftNode):
    """Stage 1 as most people first write it: elections and heartbeats work, but the leader
    acks a command as soon as it is in its own log (nothing is replicated)."""

    async def on_command(self, msg):
        if self.role != "leader":
            self.reply(msg, {"type": "command_redirect", "leader": self.leader_id})
            return
        self.log.append(ref.Entry(self.current_term, msg.body["value"]))
        self.reply(msg, {"type": "command_ok"})

    def replicate(self, peer):  # heartbeats only
        if peer in self.in_flight or self.now() - self.last_sent.get(peer, -1.0) < ref.HEARTBEAT:
            return
        body = {"type": "append_entries", "term": self.current_term, "leader": self.node_id,
                "prev_index": 0, "prev_term": 0, "entries": [], "commit": 0}
        self.in_flight.add(peer)
        self.last_sent[peer] = self.now()
        self.spawn(self.beat(peer, body))

    async def beat(self, peer, body):
        try:
            await self.rpc(peer, body, timeout=ref.RPC_TIMEOUT)
        finally:
            self.in_flight.discard(peer)

    async def on_append_entries(self, msg):
        b = msg.body
        if b["term"] >= self.current_term:
            self.become_follower(b["term"], b["leader"])
            self.deadline = self.now() + self.timeout()
        self.reply(msg, {"type": "append_entries_ok", "term": self.current_term,
                         "success": b["term"] >= self.current_term, "match": 0})


class _NoTermChecks(ref.RaftNode):
    """Stage 2: replicates, and commits on a majority, but never looks at the term of
    AppendEntries or of their replies (and does not count only current-term entries)."""

    async def append(self, peer, body, term):
        try:
            reply = await self.rpc(peer, body, timeout=ref.RPC_TIMEOUT)
        finally:
            self.in_flight.discard(peer)
        if self.role != "leader":
            return
        if reply["success"]:
            self.match_index[peer] = max(self.match_index[peer], reply["match"])
            self.next_index[peer] = self.match_index[peer]
            self.advance_commit()
        else:
            self.next_index[peer] = max(0, min(self.next_index[peer] - 1, reply["match"]))

    def advance_commit(self):
        for n in range(len(self.log), self.commit_index, -1):
            if 1 + sum(1 for p in self.peers if self.match_index[p] >= n) >= self.majority:
                self.commit_index = n
                break
        for index in [i for i in self.waiting if i <= self.commit_index]:
            self.reply(self.waiting.pop(index), {"type": "command_ok", "index": index})

    async def on_append_entries(self, msg):
        b = msg.body
        self.role, self.leader_id = "follower", b["leader"]  # whatever its term
        self.waiting.clear()
        self.deadline = self.now() + self.timeout()
        prev = b["prev_index"]
        if prev > len(self.log) or (prev > 0 and self.log[prev - 1].term != b["prev_term"]):
            self.reply(msg, {"type": "append_entries_ok", "term": self.current_term, "success": False,
                             "match": min(len(self.log), prev - 1)})
            return
        for i, (term, command) in enumerate(b["entries"]):
            pos = prev + i
            if pos < len(self.log) and self.log[pos].term != term:
                del self.log[pos:]
            if pos >= len(self.log):
                self.log.append(ref.Entry(term, command))
        match = prev + len(b["entries"])
        self.commit_index = max(self.commit_index, min(b["commit"], match))
        self.reply(msg, {"type": "append_entries_ok", "term": self.current_term, "success": True,
                         "match": match})


class ACKS_ALONE:
    RaftNode = _AcksAlone


class NO_TERM_CHECKS:
    RaftNode = _NoTermChecks


def first(world, v):
    return [r.ok for r in world.runs[v].settled[0]]


def cluster(cls, body):
    """Five nodes of `cls` on a network; run `body(net, nodes, client)` on virtual time."""

    async def main():
        net = Network(latency=0.02, seed=1)
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


# ------------------------------------------------------------- given behaviour


def test_starting_code_runs_but_nobody_leads():
    world = build_world("raft_consensus", "main", 1)
    assert world.stage_index("main") is not None
    piece = scenario.run("main", chunk=0)
    assert piece["tables"]["ops"] and not any(o[3] for o in piece["tables"]["ops"])


def test_acking_alone_elects_but_fails_the_commit_goal_on_every_seed():
    for seed in (1, 2, 3):
        world = build_world("raft_consensus", ACKS_ALONE, 1, seed=seed)
        assert first(world, ACKS_ALONE) == [True, True, False, True, True]
        assert world.stage_index(ACKS_ALONE) == 1  # Leader election


def test_no_term_checks_replicates_but_loses_committed_commands_after_the_split():
    for seed in (1, 2, 3):
        world = build_world("raft_consensus", NO_TERM_CHECKS, 1, seed=seed)
        assert first(world, NO_TERM_CHECKS) == [True, True, True, False, True]
        assert world.runs[NO_TERM_CHECKS].total("lost", 60) > 0
        assert world.stage_index(NO_TERM_CHECKS) == 2  # Log replication


def test_reference_passes_every_goal_on_every_incident():
    world = build_world("raft_consensus", "reference", 6, seed=3)
    run = world.runs["reference"]
    kinds = {i.kind for i in run.incidents}
    assert len(run.settled) >= 6 and {"partition", "crash"} <= kinds
    assert all(r.ok for results in run.settled.values() for r in results if r is not None)
    assert world.stage_index("reference") == 3  # Safe


def test_pieces_join_in_order_and_the_trace_stays_bounded():
    world = build_world("raft_consensus", "reference", 8)
    run = world.runs["reference"]
    assert run.keys["msgs"] == sorted(run.keys["msgs"])
    assert run.keys["ops"][0] >= 120  # the first minutes' raw rows are gone
    assert len(run.data["committed"]) < 8 * 60 * 15  # old commands are forgotten too
    pieces = itertools.islice(scenario.stream("reference"), 8)
    asked = sum(len(p["tables"]["ops"]) for p in pieces)
    assert run.total("ops", 1e9) == asked


def test_a_crash_keeps_only_what_raft_persists():
    world = build_world("raft_consensus", "reference", 2, seed=3)  # seed 3 crashes the leader at 0:58
    crash = next(i for i in world.runs["reference"].incidents if i.kind == "crash")
    assert all(r.ok for r in world.runs["reference"].settled[crash.index])


# ------------------------------------------------------------- your code


@your_code(1, "RaftNode elects exactly one leader, and the others follow its term")
def test_stage1_one_leader():
    async def body(net, nodes, client):
        await asyncio.sleep(3.0)
        return leaders(nodes), {n.current_term for n in nodes}

    found, terms = cluster(code.RaftNode, body)
    assert len(found) == 1 and len(terms) == 1


@your_code(1, "on_request_vote grants one vote per term")
def test_stage1_one_vote_per_term():
    async def body(net, nodes, client):
        node = nodes[0]
        node.current_term = 3
        a = ask(node, {"type": "request_vote", "term": 3, "candidate": "n1", "last_index": 0, "last_term": 0})
        b = ask(node, {"type": "request_vote", "term": 3, "candidate": "n2", "last_index": 0, "last_term": 0})
        c = ask(node, {"type": "request_vote", "term": 3, "candidate": "n1", "last_index": 0, "last_term": 0})
        return a["granted"], b["granted"], c["granted"]

    assert cluster(code.RaftNode, body) == (True, False, True)


@your_code(1, "a new leader is elected within 2 s when the leader is cut off")
def test_stage1_election_goal():
    world = build_world("raft_consensus", variant(), 1)
    assert first(world, variant())[:2] == [True, True]


@your_code(2, "every follower's log ends up equal to the leader's")
def test_stage2_logs_match():
    async def body(net, nodes, client):
        await asyncio.sleep(2.0)
        leader = leaders(nodes)[0].node_id
        for v in range(1, 21):
            reply = await client.rpc(leader, {"type": "command", "value": v}, timeout=1.0)
            assert reply["type"] == "command_ok"
        await asyncio.sleep(1.0)
        return [[(e.term, e.command) for e in n.log] for n in nodes]

    logs = cluster(code.RaftNode, body)
    assert len(logs[0]) == 20 and all(lg == logs[0] for lg in logs)


@your_code(2, "a command is acked only once a majority stores it")
def test_stage2_commit_goal():
    world = build_world("raft_consensus", variant(), 1)
    assert first(world, variant())[COMMITTED_OK]


@your_code(3, "on_append_entries rejects an older term, and says its own")
def test_stage3_rejects_stale_leaders():
    async def body(net, nodes, client):
        node = nodes[0]
        node.current_term = 5
        stale = ask(node, {"type": "append_entries", "term": 3, "leader": "n1", "prev_index": 0,
                           "prev_term": 0, "entries": [(3, 99)], "commit": 1})
        log = list(node.log)
        current = ask(node, {"type": "append_entries", "term": 5, "leader": "n2", "prev_index": 0,
                             "prev_term": 0, "entries": [(5, 7)], "commit": 0})
        return stale, log, current, [(e.term, e.command) for e in node.log]

    stale, before, current, after = cluster(code.RaftNode, body)
    assert stale["success"] is False and stale["term"] == 5 and before == []
    assert current["success"] is True and after == [(5, 7)]  # the current leader is followed


@your_code(3, "a node that sees a higher term becomes a follower of it")
def test_stage3_steps_down():
    async def body(net, nodes, client):
        await asyncio.sleep(2.0)
        leader = leaders(nodes)[0]
        term = leader.current_term
        ask(leader, {"type": "request_vote", "term": term + 5, "candidate": "n9", "last_index": 0,
                     "last_term": 0})
        return leader.role, leader.current_term - term

    assert cluster(code.RaftNode, body) == ("follower", 5)


@your_code(3, "nothing committed is lost when the old leader comes back")
def test_stage3_safe_goal():
    world = build_world("raft_consensus", variant(), 1)
    assert first(world, variant()) == [True] * 5
    assert world.stage_index(variant()) == 3


def test_a_second_picture_shows_what_the_clients_see():
    from live.canvas import RED
    from live.views import adapter_for, set_view, views_for

    world = build_world("raft_consensus", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights or frame.outcomes
    text, colour = frame.state
    assert text and len(text) <= 13
    # there is a leader (the door is open), and no acknowledged command is uncommitted (red)
    assert not frame.closed and RED not in [c for c, _ in frame.outcomes]
