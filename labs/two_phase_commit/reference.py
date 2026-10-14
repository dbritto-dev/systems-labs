"""Lab two_phase_commit: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio

from core.net import Message, Node

COORDINATOR = "n0"
RPC_TIMEOUT = 0.5  # seconds to wait for a vote or an acknowledgement
RETRY = 0.5  # seconds between two tries of a decision that was not acknowledged
ASK_EVERY = 0.5  # how often a shard asks about the transfers it is in doubt about ...
ASK_AFTER = 1.0  # ... once they have been prepared this long


class Coordinator(Node):
    def __init__(self, node_id: str, node_ids: list[str], log) -> None:
        super().__init__(node_id, node_ids)
        self.log = log
        self.active: set[str] = set()  # transfers still collecting votes (lost in a crash)

    async def recover(self) -> None:
        # The log says which transfers were decided "commit": tell every shard again.
        for txn, decision, shards in self.log.items():
            self.spawn(self.finish(txn, decision, shards))

    async def on_transfer(self, msg: Message) -> None:
        txn, writes = msg.body["txn"], msg.body["writes"]
        committed = await self.two_phase(txn, writes)
        self.reply(msg, {"type": "transfer_ok", "committed": committed})

    async def two_phase(self, txn: str, writes: dict) -> bool:
        """Prepare everywhere; commit only if every shard voted yes. Log the decision first."""
        self.active.add(txn)
        try:
            votes = await asyncio.gather(*(self.vote(shard, txn, account, delta)
                                           for shard, (account, delta) in writes.items()))
            decision = "commit" if all(votes) else "abort"
            if decision == "commit":
                await self.log.write(txn, decision, list(writes))  # the commit point: durable first
        finally:
            self.active.discard(txn)
        # Commits must reach everyone; an abort need not (presumed abort: a shard that asks about a
        # transaction the log does not know is told "abort").
        self.spawn(self.finish(txn, decision, list(writes)))
        return decision == "commit"

    async def finish(self, txn: str, decision: str, shards: list[str]) -> None:
        await asyncio.gather(*(self.deliver(shard, txn, decision) for shard in shards))
        if decision == "commit":
            self.log.forget(txn)  # every shard has it: nobody will ask again

    async def vote(self, shard: str, txn: str, account: str, delta: int) -> bool:
        try:
            reply = await self.rpc(shard, {"type": "prepare", "txn": txn, "account": account, "delta": delta},
                                   timeout=RPC_TIMEOUT)
        except TimeoutError:
            return False  # no answer is a no
        return reply.get("vote") is True

    async def deliver(self, shard: str, txn: str, decision: str) -> None:
        """Send the decision until the shard acknowledges it (a commit); an abort goes once."""
        while True:
            try:
                await self.rpc(shard, {"type": decision, "txn": txn}, timeout=RPC_TIMEOUT)
                return
            except TimeoutError:
                if decision != "commit":
                    return
                await self.sleep(RETRY)

    async def on_status(self, msg: Message) -> None:
        txn = msg.body["txn"]
        decision = self.log.read(txn)
        if decision is None and txn not in self.active:
            decision = "abort"  # never logged, not deciding: it was never committed
        self.reply(msg, {"type": "status_ok", "decision": decision})


class Shard(Node):
    def __init__(self, node_id: str, node_ids: list[str], db) -> None:
        super().__init__(node_id, node_ids)
        self.db = db

    async def recover(self) -> None:
        # Prepared transfers survive a crash on disk, with their locks: find out how each one ended.
        self.every(ASK_EVERY, self.ask)

    async def on_write(self, msg: Message) -> None:
        ok = await self.db.write(msg.body["txn"], msg.body["account"], msg.body["delta"])
        self.reply(msg, {"type": "write_ok", "ok": ok})

    async def on_prepare(self, msg: Message) -> None:
        vote = await self.db.prepare(msg.body["txn"], msg.body["account"], msg.body["delta"])
        self.reply(msg, {"type": "prepare_ok", "vote": vote})

    async def on_commit(self, msg: Message) -> None:
        self.db.commit(msg.body["txn"])
        self.reply(msg, {"type": "commit_ok"})

    async def on_abort(self, msg: Message) -> None:
        self.db.abort(msg.body["txn"])
        self.reply(msg, {"type": "abort_ok"})

    async def ask(self) -> None:
        """Ask the coordinator about every transfer in doubt for a while. Never decide alone."""
        old = [txn for txn, since in self.db.in_doubt().items() if self.now() - since >= ASK_AFTER]
        await asyncio.gather(*(self.learn(txn) for txn in old))

    async def learn(self, txn: str) -> None:
        try:
            reply = await self.rpc(COORDINATOR, {"type": "status", "txn": txn}, timeout=RPC_TIMEOUT)
        except TimeoutError:
            return  # the coordinator is down or cut off: keep the locks, ask again later
        if reply.get("decision") == "commit":
            self.db.commit(txn)
        elif reply.get("decision") == "abort":
            self.db.abort(txn)
