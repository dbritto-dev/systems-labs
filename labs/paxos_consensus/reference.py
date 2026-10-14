"""Lab paxos_consensus: a working solution (every stage). Read it after you have tried main.py."""

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

    # ---- clients (stage 2: only the leader proposes; the others redirect)

    async def on_command(self, msg: Message) -> None:
        value = msg.body["value"]
        if self.role != "leader":  # the client tries the leader you name (None: nobody yet)
            self.reply(msg, {"type": "command_redirect", "leader": self.leader_id})
            return
        self.waiting[value] = msg  # learn() answers it once it is applied
        slot = self.next_slot
        self.next_slot += 1
        self.spawn(self.phase2(slot, value))

    # ---- stage 0 (given): the first proposal a node hears wins

    async def on_propose(self, msg: Message) -> None:
        slot = msg.body["slot"]
        if slot not in self.decided:
            self.learn(slot, msg.body["value"])  # the first value a node hears for a slot wins
        self.busy.discard(slot)

    # ---- the acceptor (stage 1)

    async def on_prepare(self, msg: Message) -> None:
        b = msg.body
        if b["ballot"] > self.promised:
            self.promised = b["ballot"]
            self.see(b["ballot"])
            if self.role != "follower" and b["ballot"] > self.ballot:
                self.step_down()  # someone else stands with a higher ballot
            self.deadline = self.now() + self.timeout()  # give the candidate time to win
            self.reply(msg, {"type": "promise", "ok": True, "accepted": self.accepted_from(b["slot"])})
        else:
            self.reply(msg, {"type": "promise", "ok": False, "promised": self.promised})

    async def on_accept(self, msg: Message) -> None:
        b = msg.body
        if b["ballot"] >= self.promised:
            self.promised = b["ballot"]
            self.accepted[b["slot"]] = (b["ballot"], b["value"])
            self.follow(b["ballot"])
            self.reply(msg, {"type": "accepted", "ok": True})
        else:
            self.reply(msg, {"type": "accepted", "ok": False, "promised": self.promised})

    # ---- the proposer (stage 1): one full Paxos round per slot

    async def submit(self, value: int) -> None:
        """Propose `value` slot after slot until it is chosen in one of them."""
        start, tries = self.now(), 0
        async with self.proposing:  # one round at a time per node
            while value in self.waiting and self.now() - start < GIVE_UP:
                slot = self.free_slot()
                self.busy.add(slot)
                try:
                    chosen = await self.paxos(slot, value)
                finally:
                    self.busy.discard(slot)
                if chosen == value:
                    return
                if chosen is None:  # outbid: wait a random moment, or proposers outbid each other forever
                    tries += 1
                    await self.sleep(self.rng.uniform(0, BACKOFF * 2 ** min(tries, 4)))

    async def paxos(self, slot: int, value: int) -> int | None:
        """Single-decree Paxos for one slot. The value chosen there, or None if a higher ballot won."""
        ballot = self.next_ballot(max(self.promised, self.highest))
        self.see(ballot)
        replies = await self.broadcast({"type": "prepare", "ballot": ballot, "slot": slot})
        oks = self.count(replies)
        if len(oks) < self.majority:
            return None
        # Some acceptor may have accepted a value here already: it may be chosen, so propose it.
        prior = [r["accepted"][slot] for r in oks if slot in r["accepted"]]
        if prior:
            value = max(prior)[1]  # the one with the highest ballot
        replies = await self.broadcast({"type": "accept", "ballot": ballot, "slot": slot, "value": value})
        if len(self.count(replies)) < self.majority:
            return None
        self.decide(slot, value)
        return value

    # ---- Multi-Paxos (stage 2): one leader, phase 1 once for every slot

    async def tick(self) -> None:
        if self.role == "leader":
            upto = self.first_undecided()
            for peer in self.peers:
                if self.now() - self.last_sent.get(peer, -1.0) >= HEARTBEAT:
                    self.last_sent[peer] = self.now()
                    self.send(peer, {"type": "heartbeat", "ballot": self.ballot, "upto": upto})
        elif self.role == "follower" and self.now() >= self.deadline:
            self.spawn(self.campaign())

    async def campaign(self) -> None:
        """Phase 1 once, for every slot from the first undecided one on."""
        ballot = self.next_ballot(max(self.promised, self.highest))
        self.see(ballot)
        self.role, self.ballot, self.leader_id = "candidate", ballot, None
        self.deadline = self.now() + self.timeout()  # if it fails, wait a random time before the next try
        start = self.first_undecided()
        replies = await self.broadcast({"type": "prepare", "ballot": ballot, "slot": start})
        oks = self.count(replies)
        if self.role != "candidate" or len(oks) < self.majority or self.highest > ballot:
            if self.role == "candidate":
                self.role = "follower"
            return
        self.role, self.leader_id = "leader", self.node_id
        self.last_sent.clear()
        # Every value some acceptor accepted may be chosen: propose it again, with the new ballot.
        best: dict[int, tuple[int, int]] = {}
        for r in oks:
            for slot, (b, v) in r["accepted"].items():
                if slot >= start and (slot not in best or b > best[slot][0]):
                    best[slot] = (b, v)
        top = max(best, default=start - 1)
        self.next_slot = top + 1
        for slot in range(start, top + 1):
            if slot not in self.decided:  # a gap nobody accepted anything in: fill it with a no-op
                self.spawn(self.phase2(slot, best[slot][1] if slot in best else NOOP))

    async def phase2(self, slot: int, value: int) -> None:
        """Accept, then decide, without a prepare: the leader's ballot holds for every slot."""
        ballot = self.ballot
        body = {"type": "accept", "ballot": ballot, "slot": slot, "value": value}
        got: set[str] = set()

        async def one(node: str) -> None:
            while self.role == "leader" and self.ballot == ballot and slot not in self.decided:
                self.last_sent[node] = self.now()
                try:
                    reply = await self.rpc(node, body, RPC_TIMEOUT)
                except TimeoutError:
                    continue  # lost: send it again
                if not reply.get("ok"):
                    self.preempted(reply.get("promised", 0))
                    return
                got.add(node)
                if len(got) >= self.majority and slot not in self.decided:
                    self.decide(slot, value)
                return

        for node in self.node_ids:
            self.spawn(one(node))

    async def on_heartbeat(self, msg: Message) -> None:
        b = msg.body
        if b["ballot"] < self.promised:  # a deposed leader that does not know it yet
            self.send(msg.src, {"type": "preempt", "promised": self.promised})
            return
        self.follow(b["ballot"], msg.src)
        if b["upto"] > self.first_undecided():
            self.spawn(self.catch_up(msg.src))
