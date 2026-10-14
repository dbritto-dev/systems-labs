"""Laboratorio two_phase_commit: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio

from core.net import Message, Node

COORDINATOR = "n0"
RPC_TIMEOUT = 0.5  # segundos de espera para un voto o una confirmación
RETRY = 0.5  # segundos entre dos intentos de una decisión que no se confirmó
ASK_EVERY = 0.5  # cada cuánto pregunta un fragmento por las transferencias en duda ...
ASK_AFTER = 1.0  # ... cuando llevan este tiempo preparadas


class Coordinator(Node):
    def __init__(self, node_id: str, node_ids: list[str], log) -> None:
        super().__init__(node_id, node_ids)
        self.log = log
        self.active: set[str] = set()  # transferencias que aún reúnen votos (se pierden en una caída)

    async def recover(self) -> None:
        # El registro dice qué transferencias se decidieron "commit": díselo otra vez a cada fragmento.
        for txn, decision, shards in self.log.items():
            self.spawn(self.finish(txn, decision, shards))

    async def on_transfer(self, msg: Message) -> None:
        txn, writes = msg.body["txn"], msg.body["writes"]
        committed = await self.two_phase(txn, writes)
        self.reply(msg, {"type": "transfer_ok", "committed": committed})

    async def two_phase(self, txn: str, writes: dict) -> bool:
        """Prepara en todos; consolida solo si todos votaron sí. Registra la decisión primero."""
        self.active.add(txn)
        try:
            votes = await asyncio.gather(*(self.vote(shard, txn, account, delta)
                                           for shard, (account, delta) in writes.items()))
            decision = "commit" if all(votes) else "abort"
            if decision == "commit":
                await self.log.write(txn, decision, list(writes))  # el punto de consolidación: duradero primero
        finally:
            self.active.discard(txn)
        # Una consolidación tiene que llegar a todos; un aborto no (aborto presunto: a un fragmento que
        # pregunta por una transacción que el registro no conoce se le dice "abort").
        self.spawn(self.finish(txn, decision, list(writes)))
        return decision == "commit"

    async def finish(self, txn: str, decision: str, shards: list[str]) -> None:
        await asyncio.gather(*(self.deliver(shard, txn, decision) for shard in shards))
        if decision == "commit":
            self.log.forget(txn)  # todos los fragmentos la tienen: nadie volverá a preguntar

    async def vote(self, shard: str, txn: str, account: str, delta: int) -> bool:
        try:
            reply = await self.rpc(shard, {"type": "prepare", "txn": txn, "account": account, "delta": delta},
                                   timeout=RPC_TIMEOUT)
        except TimeoutError:
            return False  # sin respuesta es un no
        return reply.get("vote") is True

    async def deliver(self, shard: str, txn: str, decision: str) -> None:
        """Envía la decisión hasta que el fragmento la confirme (una consolidación); un aborto va una vez."""
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
            decision = "abort"  # nunca se registró y no se está decidiendo: nunca se consolidó
        self.reply(msg, {"type": "status_ok", "decision": decision})


class Shard(Node):
    def __init__(self, node_id: str, node_ids: list[str], db) -> None:
        super().__init__(node_id, node_ids)
        self.db = db

    async def recover(self) -> None:
        # Las transferencias preparadas sobreviven a una caída en disco, con sus bloqueos: averigua cómo
        # terminó cada una.
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
        """Pregunta al coordinador por cada transferencia que lleva un rato en duda. Nunca decidas solo."""
        old = [txn for txn, since in self.db.in_doubt().items() if self.now() - since >= ASK_AFTER]
        await asyncio.gather(*(self.learn(txn) for txn in old))

    async def learn(self, txn: str) -> None:
        try:
            reply = await self.rpc(COORDINATOR, {"type": "status", "txn": txn}, timeout=RPC_TIMEOUT)
        except TimeoutError:
            return  # el coordinador está caído o aislado: mantén los bloqueos y vuelve a preguntar luego
        if reply.get("decision") == "commit":
            self.db.commit(txn)
        elif reply.get("decision") == "abort":
            self.db.abort(txn)
