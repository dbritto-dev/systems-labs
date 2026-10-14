"""Lab paxos_consensus: YOUR FILE. Edit it and save; the live window reruns it.

5 nodes ("n0" ... "n4") keep a replicated log of config changes: slot 0, 1, 2, ... each holds one
command (a number). Clients send `{"type": "command", "value": 17}` to any node; several nodes
propose at once. A node answers the client `command_ok` once the command is decided in a slot and
applied there (learn() does it for you). Every node must decide the same value in every slot, and
no answered command may vanish. Right now each node keeps the first value it hears for a slot, so
two proposers racing for one slot split the cluster: some nodes decide one command, some the other.

Do the stages in order, in this file:

  Stage 1  Single-decree Paxos per slot. A proposer picks a ballot higher than any it has seen and
           sends `prepare`; an acceptor promises to ignore lower ballots and says what it already
           accepted. With a majority of promises, the proposer must propose the accepted value with
           the highest ballot (it may already be chosen), else its own, with `accept`. A majority of
           accepts decides it. Safe, but two proposers keep outbidding each other (they duel), and
           every command costs two round trips to everyone.
  Stage 2  Multi-Paxos with a stable leader. A node that hears no leader for a random timeout runs
           phase 1 once, for every slot from its first undecided one on (`campaign`); then it leads:
           every command is only an `accept` round (`phase2`), and the others redirect clients to it.
           A new leader proposes again every value its promises reported, and fills each gap (a slot
           nobody accepted anything in) with a no-op, or the log stops applying there.

Incidents come at random: the leader crashes in the middle of a round, another node crashes, the
network loses and delays messages, a partition cuts the leader off with one node, or the leader
stops for seconds (a GC pause) and wakes up still sure it leads. A crashed node restarts with what
Paxos keeps on disk: promised, accepted and decided. The first incident is always the leader dying
while it sends its accepts, at 0:20 (back at 0:30).

The protocol (the checker reads `decided`, `accepted` and `promised`; the pictures read the types):
  propose  {slot, value}                    stage 0: the first one a node hears for a slot wins
  prepare  {ballot, slot}  -> promise {ok, accepted: {slot: [ballot, value]} from that slot on}
                                          or {ok: False, promised}
  accept   {ballot, slot, value} -> accepted {ok} or {ok: False, promised}
  decide   {slot, value}                    tell the others (learn() records it)
  heartbeat {ballot, upto}                  stage 2: the leader is alive; upto = its first undecided slot
  command  {value} -> command_ok, or command_redirect {leader}    (client -> any node)

How your node talks (see core/net.py): self.node_id, self.node_ids, self.reply(msg, {...}),
self.send(dest, {...}), await self.rpc(dest, {...}, timeout), self.spawn(coroutine),
self.every(seconds, coroutine_function), self.now(); and the helpers below:
`await self.broadcast(body)` (everyone, you included; the replies once a majority answered),
`self.next_ballot(above)`, `self.learn(slot, value)`, `self.decide(slot, value)` (learn and tell the
others), `self.free_slot()`, `self.first_undecided()`, `self.accepted_from(slot)`.

Check yourself:  uv run pytest labs/paxos_consensus
Peek at a solution (after trying!):  labs/paxos_consensus/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.net import Message, Node, RPCError

NOOP = 0  # the value that fills a gap in the log: it changes nothing when applied
TICK = 0.02  # how often tick() runs
HEARTBEAT = 0.15  # the leader sends every node something at least this often
ELECTION_TIMEOUT = (0.3, 0.6)  # seconds without hearing a leader before standing for election
RPC_TIMEOUT = 0.15  # seconds to wait for a reply before sending again
BACKOFF = 0.05  # stage 1: a proposer outbid waits up to this, doubled after each try
GIVE_UP = 2.0  # stage 1: a proposer stops trying for a command after this long (the client is gone)
SYNC_BATCH = 200  # decided slots per sync reply at most


class PaxosNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        # On disk: survives a crash (the scenario copies it into the restarted node).
        self.promised = 0  # the highest ballot this acceptor promised (for every slot)
        self.accepted: dict[int, tuple[int, int]] = {}  # slot -> (ballot, value) it accepted
        self.decided: dict[int, int] = {}  # slot -> the value decided there
        # In memory: a crash loses it.
        self.applied = 0  # slots 0 .. applied-1 are decided and applied, in order
        self.waiting: dict[int, Message] = {}  # value -> the client request to answer once it is applied
        self.busy: set[int] = set()  # slots this node is proposing for right now
        self.proposing = asyncio.Lock()  # stage 1: a node runs one Paxos round at a time
        self.highest = 0  # the highest ballot this node has seen anywhere
        self.role = "follower"  # "follower", "candidate" or "leader"
        self.leader_id: str | None = None
        self.ballot = 0  # the ballot this node stands or leads with
        self.next_slot = 0  # the leader's next free slot
        self.index = node_ids.index(node_id)
        self.majority = len(node_ids) // 2 + 1
        self.peers = [n for n in node_ids if n != node_id]
        self.rng = random.Random(node_id)  # its own timeouts: nodes must not time out together
        self.deadline = self.now() + self.timeout()
        self.last_sent: dict[str, float] = {}
        self.syncing = False
        self.every(TICK, self.tick)

    # ---- given: the log, ballots, talking to everyone

    def learn(self, slot: int, value: int) -> None:
        """Record a decided value, apply the log in order, and answer the clients whose command
        was just applied here."""
        if slot in self.decided:
            return
        self.decided[slot] = value
        while self.applied in self.decided:
            msg = self.waiting.pop(self.decided[self.applied], None)
            if msg is not None:
                self.reply(msg, {"type": "command_ok", "slot": self.applied})
            self.applied += 1

    def first_undecided(self) -> int:
        """The lowest slot this node does not know the value of."""
        while self.applied in self.decided:
            self.applied += 1
        return self.applied

    def free_slot(self) -> int:
        """The lowest undecided slot this node is not already proposing for."""
        slot = self.first_undecided()
        while slot in self.decided or slot in self.busy:
            slot += 1
        return slot

    def next_ballot(self, above: int) -> int:
        """The smallest ballot above `above` that is this node's own (ballot % 5 == its index)."""
        n = len(self.node_ids)
        return (above // n + 1) * n + self.index

    def owner(self, ballot: int) -> str:
        return self.node_ids[ballot % len(self.node_ids)]

    def timeout(self) -> float:
        return self.rng.uniform(*ELECTION_TIMEOUT)

    def accepted_from(self, slot: int) -> dict[int, list[int]]:
        """What this acceptor accepted in every slot from `slot` on: {slot: [ballot, value]}."""
        return {s: [b, v] for s, (b, v) in self.accepted.items() if s >= slot}

    async def broadcast(self, body: dict, timeout: float = RPC_TIMEOUT) -> list[dict]:
        """Send `body` to every node (this one too) and return the replies: as soon as a majority
        said ok, or too many refused for a majority, or after `timeout`."""
        replies: list[dict] = []
        done = asyncio.get_running_loop().create_future()
        n = len(self.node_ids)

        async def one(node: str) -> None:
            try:
                reply = await self.rpc(node, body, timeout)
            except (TimeoutError, RPCError):
                return
            replies.append(reply)
            oks = sum(1 for r in replies if r.get("ok"))
            if not done.done() and (oks >= self.majority or len(replies) - oks > n - self.majority
                                    or len(replies) == n):
                done.set_result(None)

        for node in self.node_ids:
            self.spawn(one(node))
        try:
            async with asyncio.timeout(timeout):
                await done
        except TimeoutError:
            pass
        return list(replies)

    def count(self, replies: list[dict]) -> list[dict]:
        """The ok replies; remember the ballots of the refusals (see `self.highest`)."""
        for r in replies:
            if not r.get("ok"):
                self.see(r.get("promised", 0))
        return [r for r in replies if r.get("ok")]

    def see(self, ballot: int) -> None:
        self.highest = max(self.highest, ballot)

    def decide(self, slot: int, value: int) -> None:
        """A majority accepted `value` in `slot`: learn it, and tell the others."""
        self.learn(slot, value)
        for peer in self.peers:
            self.send(peer, {"type": "decide", "slot": slot, "value": value})

    async def on_decide(self, msg: Message) -> None:
        self.learn(msg.body["slot"], msg.body["value"])

    async def on_sync(self, msg: Message) -> None:
        """A node that is behind asks for the decided values from a slot on."""
        start = msg.body["from"]
        top = self.first_undecided()
        decided = {s: self.decided[s] for s in range(start, min(top, start + SYNC_BATCH))}
        self.reply(msg, {"type": "sync_ok", "decided": decided})

    async def catch_up(self, node: str) -> None:
        """Ask `node` for the decided values this node is missing."""
        if self.syncing:
            return
        self.syncing = True
        try:
            reply = await self.rpc(node, {"type": "sync", "from": self.first_undecided()}, RPC_TIMEOUT)
            for slot, value in reply["decided"].items():
                self.learn(slot, value)
        finally:
            self.syncing = False

    # ---- given: following a leader (stage 2 calls these)

    def follow(self, ballot: int, leader: str | None = None) -> None:
        """Someone with `ballot` leads: follow it (and step down if it outranks this node)."""
        self.see(ballot)
        if self.role != "follower" and ballot > self.ballot and self.owner(ballot) != self.node_id:
            self.step_down()
        if self.role == "follower":
            self.leader_id = leader or self.owner(ballot)
            self.deadline = self.now() + self.timeout()

    def preempted(self, promised: int) -> None:
        """An acceptor refused this node's ballot: it promised `promised`."""
        self.see(promised)
        if self.role != "follower" and promised > self.ballot:
            self.step_down()

    def step_down(self) -> None:
        self.role, self.leader_id = "follower", None
        self.waiting.clear()  # the clients will try the new leader
        self.deadline = self.now() + self.timeout()  # a random backoff before standing again

    async def on_preempt(self, msg: Message) -> None:
        self.preempted(msg.body["promised"])

    # ---- stage 0 (given): the first proposal a node hears wins

    async def on_command(self, msg: Message) -> None:
        value = msg.body["value"]
        # Stage 2: if self.role != "leader", reply {"type": "command_redirect", "leader": self.leader_id}
        #          and return; else keep it in self.waiting, take slot self.next_slot (then += 1), and
        #          self.spawn(self.phase2(slot, value)).
        self.waiting[value] = msg  # learn() answers it once it is applied here
        # Stage 1: replace the lines below with `self.spawn(self.submit(value))`.
        slot = self.free_slot()
        self.busy.add(slot)
        for node in self.node_ids:
            self.send(node, {"type": "propose", "slot": slot, "value": value})

    async def on_propose(self, msg: Message) -> None:
        slot = msg.body["slot"]
        if slot not in self.decided:
            self.learn(slot, msg.body["value"])  # the first value a node hears for a slot wins
        self.busy.discard(slot)

    # ---- the acceptor (stage 1)

    async def on_prepare(self, msg: Message) -> None:
        """Stage 1. If msg.body["ballot"] > self.promised: promise it (self.promised = ballot) and
        reply {"type": "promise", "ok": True, "accepted": self.accepted_from(msg.body["slot"])}.
        Else reply {"type": "promise", "ok": False, "promised": self.promised}.

        Stage 2: after promising, if you are not a follower and the ballot is higher than
        self.ballot, someone else stands with a higher ballot: self.step_down(). And push
        self.deadline back (self.now() + self.timeout()) to give the candidate time to win."""
        raise NotImplementedError("TODO stage 1: PaxosNode.on_prepare")

    async def on_accept(self, msg: Message) -> None:
        """Stage 1. If msg.body["ballot"] >= self.promised: self.promised = ballot,
        self.accepted[slot] = (ballot, value), reply {"type": "accepted", "ok": True}.
        Else reply {"type": "accepted", "ok": False, "promised": self.promised}.

        Stage 2: when you accept, the leader is alive: self.follow(ballot)."""
        raise NotImplementedError("TODO stage 1: PaxosNode.on_accept")

    # ---- the proposer (stage 1): one full Paxos round per slot

    async def submit(self, value: int) -> None:
        """Stage 1. Propose `value` slot after slot until it is chosen in one of them. Hold
        `async with self.proposing:` (one round at a time per node) and, while value is still in
        self.waiting (learn() takes it out once applied) and for at most GIVE_UP seconds: take
        slot = self.free_slot(), add it to self.busy while you run `chosen = await self.paxos(slot,
        value)` (discard it after), and stop when chosen == value. Another value: it was already
        chosen there, go on. None (outbid by a higher ballot): sleep a random
        self.rng.uniform(0, BACKOFF * 2 ** tries) first (tries up to 4), or the proposers keep
        outbidding each other."""
        raise NotImplementedError("TODO stage 1: PaxosNode.submit")

    async def paxos(self, slot: int, value: int) -> int | None:
        """Stage 1. Single-decree Paxos for one slot; return the value chosen there, or None.
          1. ballot = self.next_ballot(max(self.promised, self.highest)); self.see(ballot).
          2. oks = self.count(await self.broadcast({"type": "prepare", "ballot": ballot, "slot": slot}));
             fewer than self.majority: return None.
          3. If any ok reply has r["accepted"][slot], propose the value of the one with the highest
             ballot instead of yours (it may already be chosen: never overwrite it).
          4. Same with {"type": "accept", "ballot": ballot, "slot": slot, "value": value}; with a
             majority of oks, self.decide(slot, value) and return value; else None.
        """
        raise NotImplementedError("TODO stage 1: PaxosNode.paxos")

    # ---- Multi-Paxos (stage 2): one leader, phase 1 once for every slot

    async def tick(self) -> None:
        # Stage 2: a leader sends {"type": "heartbeat", "ballot": self.ballot, "upto": self.first_undecided()}
        # to each peer it sent nothing to for HEARTBEAT seconds (self.last_sent[peer]). A follower
        # whose self.deadline has passed stands for election: self.spawn(self.campaign()).
        return

    async def campaign(self) -> None:
        """Stage 2. Phase 1 once, for every slot from start = self.first_undecided() on.
          - ballot = self.next_ballot(max(self.promised, self.highest)); self.see(ballot);
            self.role, self.ballot, self.leader_id = "candidate", ballot, None; push self.deadline
            back by a random self.timeout() (the backoff if this attempt fails: standing again at
            once, or after a fixed wait, makes candidates duel forever).
          - oks = self.count(await self.broadcast({"type": "prepare", "ballot": ballot, "slot": start})).
            If you are no longer the candidate, or have fewer than self.majority oks, or
            self.highest > ballot: be a follower again and return.
          - Lead: self.role, self.leader_id = "leader", self.node_id.
          - For each slot from start to the highest slot any promise reported, unless you know it
            decided: self.spawn(self.phase2(slot, v)) where v is the value with the highest ballot
            the promises reported there, or NOOP if none did (a gap). self.next_slot = that top + 1.
        """
        raise NotImplementedError("TODO stage 2: PaxosNode.campaign")

    async def phase2(self, slot: int, value: int) -> None:
        """Stage 2. Accept, then decide, with no prepare: the leader's ballot holds for every slot.
        To every node (spawn one sender each), while you still lead with that ballot and the slot is
        not decided: self.last_sent[node] = self.now(); rpc {"type": "accept", "ballot": self.ballot,
        "slot": slot, "value": value} with RPC_TIMEOUT; on TimeoutError send it again; a refusal
        (ok False) means self.preempted(reply["promised"]). Once a majority accepted:
        self.decide(slot, value)."""
        raise NotImplementedError("TODO stage 2: PaxosNode.phase2")

    async def on_heartbeat(self, msg: Message) -> None:
        """Stage 2. If msg.body["ballot"] < self.promised, the sender was deposed and does not know:
        self.send(msg.src, {"type": "preempt", "promised": self.promised}) and return. Else
        self.follow(ballot, msg.src); and if msg.body["upto"] > self.first_undecided(), you missed
        decisions: self.spawn(self.catch_up(msg.src))."""
        raise NotImplementedError("TODO stage 2: PaxosNode.on_heartbeat")
