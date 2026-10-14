"""Lab two_phase_commit: YOUR FILE. Edit it and save; the live window reruns it.

A bank keeps its accounts on 3 shards ("n1", "n2", "n3"). Every transfer touches all three: it
takes money from a customer on one shard, pays a merchant on another and the bank's fee on the third,
and the three amounts add up to zero. Clients send transfers to your `Coordinator` ("n0"). Right now
it writes to one shard at a time: when a shard says no (a lock timeout, a constraint) or crashes half
way, the shards before it keep their writes. Money is created or destroyed.

Do the stages in order, in this file:

  Stage 1  Two-phase commit. Phase 1: ask every shard to `prepare` (each one locks its row, checks
           it, writes a prepare record to disk, and votes yes or no). Phase 2: only if every shard
           voted yes, send them all "commit"; otherwise send "abort". A shard that voted yes holds
           its row locked until it hears the decision: it can no longer say no.
  Stage 2  A decision log, and recovery. The coordinator can crash after collecting the votes,
           before or after sending the decision, and messages get lost.
           - Write a "commit" decision to `self.log` BEFORE sending it: that is the commit point.
           - Send a commit until every shard acknowledges it; in `recover()` (a restarted
             coordinator) send again every commit the log still holds.
           - A shard in doubt (prepared, no decision yet) asks the coordinator ("status") until it
             learns the outcome. It never decides alone: its locks wait for the answer.
           - Answer "status" from the log; a transfer the log does not know, and that you are not
             deciding right now, was never committed: answer "abort" (presumed abort).

The protocol (shards reply to every request):
  transfer {txn, writes: {shard: [account, delta]}}  -> transfer_ok {committed: bool}  (client -> n0)
  write    {txn, account, delta}  -> write_ok {ok: bool}       (stage 0: apply it now)
  prepare  {txn, account, delta}  -> prepare_ok {vote: bool}
  commit   {txn} -> commit_ok          abort {txn} -> abort_ok
  status   {txn} -> status_ok {decision: "commit" | "abort" | None}   (shard -> n0)

What you get (see labs/two_phase_commit/api.py and core/net.py):
  Shard: self.db -> await db.write(...), await db.prepare(txn, account, delta) -> bool,
         db.commit(txn), db.abort(txn), db.in_doubt() -> {txn: prepared_at}. The db is on disk:
         a restarted shard has the same one, prepared transfers and locks included.
  Coordinator: self.log -> await log.write(txn, decision, shards), log.read(txn), log.items(),
         log.forget(txn). On disk too: the rest of your memory is lost in a crash.
  Both: self.reply, self.send, await self.rpc(dest, body, timeout) (TimeoutError if no answer),
        self.spawn(coroutine), self.every(seconds, coroutine_function), await self.sleep(s), self.now().
  `recover()` is called every time a node starts: at 0:00, and again after every crash.

Check yourself:  uv run pytest labs/two_phase_commit
Peek at a solution (after trying!):  labs/two_phase_commit/reference.py
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node

COORDINATOR = "n0"
RPC_TIMEOUT = 0.5  # seconds to wait for a vote or an acknowledgement
RETRY = 0.5  # seconds between two tries of a decision that was not acknowledged
ASK_EVERY = 0.5  # how often a shard asks about the transfers it is in doubt about ...
ASK_AFTER = 1.0  # ... once they have been prepared this long


class Coordinator(Node):
    """Runs every transfer across the shards.

    Contract:
      - on `transfer`, apply every write on its shard, or none of them; reply
        {"type": "transfer_ok", "committed": True/False};
      - `recover()` runs when the coordinator starts, and after a crash (the same log, nothing else).
    """

    def __init__(self, node_id: str, node_ids: list[str], log) -> None:
        super().__init__(node_id, node_ids)
        self.log = log
        self.active: set[str] = set()  # transfers still collecting votes (lost in a crash)

    async def recover(self) -> None:
        # Stage 2: `for txn, decision, shards in self.log.items():` finish it again, in the background
        #          (self.spawn(self.finish(...))).
        return

    async def on_transfer(self, msg: Message) -> None:
        # Stage 1: replace the loop below with `committed = await self.two_phase(txn, writes)`.
        txn, writes = msg.body["txn"], msg.body["writes"]
        committed = True
        for shard, (account, delta) in writes.items():
            try:
                reply = await self.rpc(shard, {"type": "write", "txn": txn, "account": account, "delta": delta},
                                       timeout=RPC_TIMEOUT)
            except TimeoutError:
                committed = False
                break
            if not reply.get("ok"):
                committed = False
                break
        self.reply(msg, {"type": "transfer_ok", "committed": committed})

    async def two_phase(self, txn: str, writes: dict) -> bool:
        """Stage 1. Phase 1: `votes = await asyncio.gather(*(self.vote(shard, txn, account, delta)
        for shard, (account, delta) in writes.items()))`. Phase 2: the decision is "commit" if every
        vote is True, else "abort"; `await self.finish(txn, decision, list(writes))`. Return whether
        it committed.

        Stage 2: add txn to self.active while you collect the votes. For a commit,
        `await self.log.write(txn, "commit", list(writes))` BEFORE anything is sent, then finish in the
        background (`self.spawn(self.finish(...))`): you can answer the client once it is logged.
        """
        raise NotImplementedError("TODO stage 1: Coordinator.two_phase")

    async def finish(self, txn: str, decision: str, shards: list[str]) -> None:
        """Stage 1. Send the decision to every shard: `self.deliver(shard, txn, decision)` for each
        (gather them). Stage 2: once a commit has reached every shard, `self.log.forget(txn)`."""
        raise NotImplementedError("TODO stage 1: Coordinator.finish")

    async def vote(self, shard: str, txn: str, account: str, delta: int) -> bool:
        """Stage 1. Ask one shard to prepare: `await self.rpc(shard, {"type": "prepare", "txn": txn,
        "account": account, "delta": delta}, timeout=RPC_TIMEOUT)` and return reply["vote"].
        No answer (TimeoutError) is a no."""
        raise NotImplementedError("TODO stage 1: Coordinator.vote")

    async def deliver(self, shard: str, txn: str, decision: str) -> None:
        """Stage 1. Send it once: `self.send(shard, {"type": decision, "txn": txn})`.
        Stage 2. A commit must arrive: `await self.rpc(...)` and on TimeoutError `await
        self.sleep(RETRY)` and try again, until it is acknowledged. An abort can still go once."""
        raise NotImplementedError("TODO stage 1: Coordinator.deliver")

    async def on_status(self, msg: Message) -> None:
        """Stage 2. A shard asks how a transfer ended. Reply {"type": "status_ok", "decision": d}
        where d is self.log.read(txn); if that is None and txn is not in self.active, d = "abort"."""
        raise NotImplementedError("TODO stage 2: Coordinator.on_status")


class Shard(Node):
    """One shard: it applies the writes for its accounts, through `self.db`."""

    def __init__(self, node_id: str, node_ids: list[str], db) -> None:
        super().__init__(node_id, node_ids)
        self.db = db

    async def recover(self) -> None:
        # Stage 2: `self.every(ASK_EVERY, self.ask)`: prepared transfers survive a crash (on disk,
        #          with their locks), and so do the ones whose decision got lost on the way.
        return

    async def on_write(self, msg: Message) -> None:
        ok = await self.db.write(msg.body["txn"], msg.body["account"], msg.body["delta"])
        self.reply(msg, {"type": "write_ok", "ok": ok})

    async def on_prepare(self, msg: Message) -> None:
        """Stage 1. `vote = await self.db.prepare(txn, account, delta)`, then reply
        {"type": "prepare_ok", "vote": vote}."""
        raise NotImplementedError("TODO stage 1: Shard.on_prepare")

    async def on_commit(self, msg: Message) -> None:
        """Stage 1. `self.db.commit(txn)`, then reply {"type": "commit_ok"}."""
        raise NotImplementedError("TODO stage 1: Shard.on_commit")

    async def on_abort(self, msg: Message) -> None:
        """Stage 1. `self.db.abort(txn)`, then reply {"type": "abort_ok"}."""
        raise NotImplementedError("TODO stage 1: Shard.on_abort")

    async def ask(self) -> None:
        """Stage 2. For every txn in self.db.in_doubt() prepared at least ASK_AFTER ago, learn its
        outcome (`self.learn(txn)`, all at once with asyncio.gather)."""
        raise NotImplementedError("TODO stage 2: Shard.ask")

    async def learn(self, txn: str) -> None:
        """Stage 2. `reply = await self.rpc(COORDINATOR, {"type": "status", "txn": txn}, timeout=RPC_TIMEOUT)`;
        commit or abort as the reply says. No answer, or None: do nothing, keep the locks and ask again
        next time. Never abort on your own: the others may have committed."""
        raise NotImplementedError("TODO stage 2: Shard.learn")
