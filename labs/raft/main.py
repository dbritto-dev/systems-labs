"""Lab raft: YOUR FILE. Edit it and save; the live window reruns it.

5 nodes ("n0" ... "n4") on a network where every message takes ~20 ms. Clients send
`{"type": "command", "value": 17}` to the node they think leads. Your RaftNode must agree on
one ordered log of commands with the others (Raft: https://raft.github.io/raft.pdf, figure 2
is the whole algorithm on one page). Right now nobody ever leads, so every command fails.

Do the stages in order, in this file:

  Stage 1  Leader election: a follower that hears from no leader for a random election
           timeout becomes a candidate: current_term += 1, vote for itself, send
           RequestVote to the others; a majority of votes makes it the leader, which then
           sends heartbeats (empty AppendEntries) so the others do not stand. One vote per
           node per term.
  Stage 2  Log replication: the leader appends each command to its log and sends the new
           entries in AppendEntries (with prev_index and prev_term, so a follower can say
           "my log does not match there"). Answer the client `command_ok` only once a
           majority (counting the leader) has the entry: then it is committed.
  Stage 3  Safety: a leader cut off in a minority does not know it is deposed. Every reply
           and request carries the term: on a higher term, become a follower; reject
           AppendEntries with a lower term; vote only for a candidate whose log is at least
           as up to date as yours. Then nothing committed is ever lost.

Incidents come at random: the leader is cut off with one follower, the leader's host
crashes (it restarts later with current_term, voted_for and log: what Raft persists), or
the network gets slow. The first one always cuts the leader off at 0:20-0:30.

The checker reads self.role, self.current_term and self.log of every node (outside the
network): keep them up to date. self.log is a list of Entry(term, command).

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are, and every node
  self.reply(msg, {...})           answer a request
  await self.rpc(dest, {...}, timeout=0.25)  send and wait for the reply (TimeoutError if lost)
  self.spawn(coroutine)            run it in the background (e.g. one rpc per peer)
  self.every(seconds, coroutine_function)    run something periodically
  self.now()                       the time, in seconds

Check yourself:  uv run pytest labs/raft
Peek at a solution (after trying!):  labs/raft/reference.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from core.net import Message, Node

ELECTION_TIMEOUT = (0.3, 0.6)  # seconds without a leader before standing for election
HEARTBEAT = 0.1  # the leader sends AppendEntries at least this often
TICK = 0.05  # how often tick() runs
RPC_TIMEOUT = 0.25


@dataclass(frozen=True, slots=True)
class Entry:
    term: int
    command: int


class RaftNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        # Persistent state: survives a crash (the scenario copies it into the restarted node).
        self.current_term = 0
        self.voted_for: str | None = None
        self.log: list[Entry] = []
        # Volatile state.
        self.role = "follower"  # "follower", "candidate" or "leader"
        self.leader_id: str | None = None
        self.commit_index = 0  # how many entries of the log are committed
        self.rng = random.Random(node_id)  # its own timeouts: nodes must not time out together
        self.peers = [n for n in node_ids if n != node_id]
        self.majority = len(node_ids) // 2 + 1
        self.deadline = self.now() + self.timeout()
        self.every(TICK, self.tick)

    def timeout(self) -> float:
        return self.rng.uniform(*ELECTION_TIMEOUT)

    async def tick(self) -> None:
        # Stage 1: if you lead, send every peer a heartbeat (at least every HEARTBEAT s).
        # Otherwise, once self.now() >= self.deadline, stand for election: bump the term,
        # vote for yourself, and self.spawn() one RequestVote rpc per peer, e.g.
        #   {"type": "request_vote", "term": ..., "candidate": self.node_id,
        #    "last_index": len(self.log), "last_term": term of your last entry or 0}
        # With a majority of votes (yours included), become the leader.
        pass

    async def on_request_vote(self, msg: Message) -> None:
        # Stage 1: grant the vote if the term is current and you have not voted for someone
        # else in it (remember self.voted_for), and push your own deadline back.
        # Stage 3: on a higher term, become a follower of it first; and grant only if the
        # candidate's log is at least as up to date: (last_term, last_index) >= yours.
        self.reply(msg, {"type": "request_vote_ok", "term": self.current_term, "granted": False})

    async def on_append_entries(self, msg: Message) -> None:
        # Stage 1: a heartbeat from the leader: follow it (self.role, self.leader_id) and push
        # your election deadline back.
        # Stage 2: check that your log has prev_term at prev_index, drop any conflicting
        # entries, append the new ones, and move self.commit_index up to the leader's.
        # Stage 3: reject it (with your term) if its term is lower than yours.
        self.reply(msg, {"type": "append_entries_ok", "term": self.current_term, "success": False,
                         "match": len(self.log)})

    async def on_command(self, msg: Message) -> None:
        if self.role != "leader":  # the client tries the leader you name next
            self.reply(msg, {"type": "command_redirect", "leader": self.leader_id})
            return
        # Stage 1: the leader answers right away (this loses commands: fix it in stage 2).
        # Stage 2: append Entry(self.current_term, value) to self.log, replicate it, and
        # reply only once a majority has it (keep msg until then).
        self.reply(msg, {"type": "command_ok"})
