"""Laboratorio two_phase_commit: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un banco guarda sus cuentas en 3 fragmentos ("n1", "n2", "n3"). Cada transferencia toca los tres:
quita dinero a un cliente en uno, paga a un comercio en otro y la comisión del banco en el tercero, y
las tres cantidades suman cero. Los clientes envían las transferencias a tu `Coordinator` ("n0").
Ahora mismo escribe en un fragmento cada vez: cuando un fragmento dice que no (un timeout de bloqueo,
una restricción) o se cae a mitad, los fragmentos anteriores conservan sus escrituras. Se crea o se
destruye dinero.

Haz las etapas en orden, en este archivo:

  Etapa 1  Consolidación en dos fases. Fase 1: pide a cada fragmento que prepare (`prepare`: cada
           uno bloquea su fila, la comprueba, escribe un registro de preparación en disco, y vota sí
           o no). Fase 2: solo si todos votaron sí, envíales "commit"; si no, envía "abort". Un
           fragmento que votó sí mantiene su fila bloqueada hasta que oye la decisión: ya no puede
           decir que no.
  Etapa 2  Un log de decisiones, y recuperación. El coordinador puede caerse después de reunir
           los votos, antes o después de enviar la decisión, y se pierden mensajes.
           - Escribe la decisión "commit" en `self.log` ANTES de enviarla: es el punto de consolidación.
           - Envía una consolidación hasta que cada fragmento la confirme; en `recover()` (un
             coordinador que reinicia) vuelve a enviar cada "commit" que aún tenga el log.
           - Un fragmento en duda (preparado, sin decisión aún) pregunta al coordinador ("status")
             hasta saber el resultado. Nunca decide solo: sus bloqueos esperan la respuesta.
           - Responde a "status" desde el log; una transferencia que el log no conoce, y que
             no estás decidiendo ahora, nunca se consolidó: responde "abort" (aborto presunto).

El protocolo (los fragmentos responden a cada petición):
  transfer {txn, writes: {shard: [account, delta]}}  -> transfer_ok {committed: bool}  (cliente -> n0)
  write    {txn, account, delta}  -> write_ok {ok: bool}       (etapa 0: aplícalo ya)
  prepare  {txn, account, delta}  -> prepare_ok {vote: bool}
  commit   {txn} -> commit_ok          abort {txn} -> abort_ok
  status   {txn} -> status_ok {decision: "commit" | "abort" | None}   (fragmento -> n0)

Lo que tienes (mira labs/two_phase_commit/api.py y core/net.py):
  Shard: self.db -> await db.write(...), await db.prepare(txn, account, delta) -> bool,
         db.commit(txn), db.abort(txn), db.in_doubt() -> {txn: prepared_at}. La base de datos está en
         disco: un fragmento que reinicia tiene la misma, con sus transferencias preparadas y bloqueos.
  Coordinator: self.log -> await log.write(txn, decision, shards), log.read(txn), log.items(),
         log.forget(txn). También en disco: el resto de tu memoria se pierde en una caída.
  Ambos: self.reply, self.send, await self.rpc(dest, body, timeout) (TimeoutError si no hay respuesta),
         self.spawn(corrutina), self.every(segundos, función_corrutina), await self.sleep(s), self.now().
  `recover()` se llama cada vez que un nodo arranca: a las 0:00, y otra vez tras cada caída.

Compruébalo:  LABS_LANG=es uv run pytest labs/two_phase_commit
Mira una solución (¡después de intentarlo!):  labs/two_phase_commit/es/reference.py
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node

COORDINATOR = "n0"
RPC_TIMEOUT = 0.5  # segundos de espera para un voto o una confirmación
RETRY = 0.5  # segundos entre dos intentos de una decisión que no se confirmó
ASK_EVERY = 0.5  # cada cuánto pregunta un fragmento por las transferencias en duda ...
ASK_AFTER = 1.0  # ... cuando llevan este tiempo preparadas


class Coordinator(Node):
    """Ejecuta cada transferencia entre los fragmentos.

    Contrato:
      - ante `transfer`, aplica cada escritura en su fragmento, o ninguna; responde
        {"type": "transfer_ok", "committed": True/False};
      - `recover()` se ejecuta cuando el coordinador arranca, y tras una caída (el mismo log, nada más).
    """

    def __init__(self, node_id: str, node_ids: list[str], log) -> None:
        super().__init__(node_id, node_ids)
        self.log = log
        self.active: set[str] = set()  # transferencias que aún reúnen votos (se pierden en una caída)

    async def recover(self) -> None:
        # Etapa 2: `for txn, decision, shards in self.log.items():` termínala otra vez, en segundo plano
        #          (self.spawn(self.finish(...))).
        return

    async def on_transfer(self, msg: Message) -> None:
        # Etapa 1: cambia el bucle de abajo por `committed = await self.two_phase(txn, writes)`.
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
        """Etapa 1. Fase 1: `votes = await asyncio.gather(*(self.vote(shard, txn, account, delta)
        for shard, (account, delta) in writes.items()))`. Fase 2: la decisión es "commit" si todos los
        votos son True, si no "abort"; `await self.finish(txn, decision, list(writes))`. Devuelve si se
        consolidó.

        Etapa 2: añade txn a self.active mientras reúnes los votos. Para una consolidación,
        `await self.log.write(txn, "commit", list(writes))` ANTES de enviar nada, y luego termina en
        segundo plano (`self.spawn(self.finish(...))`): puedes responder al cliente en cuanto está
        registrada.
        """
        raise NotImplementedError("PENDIENTE etapa 1: Coordinator.two_phase")

    async def finish(self, txn: str, decision: str, shards: list[str]) -> None:
        """Etapa 1. Envía la decisión a cada fragmento: `self.deliver(shard, txn, decision)` para cada
        uno (júntalos con gather). Etapa 2: cuando una consolidación ha llegado a todos los fragmentos,
        `self.log.forget(txn)`."""
        raise NotImplementedError("PENDIENTE etapa 1: Coordinator.finish")

    async def vote(self, shard: str, txn: str, account: str, delta: int) -> bool:
        """Etapa 1. Pide a un fragmento que prepare: `await self.rpc(shard, {"type": "prepare", "txn": txn,
        "account": account, "delta": delta}, timeout=RPC_TIMEOUT)` y devuelve reply["vote"].
        Sin respuesta (TimeoutError) es un no."""
        raise NotImplementedError("PENDIENTE etapa 1: Coordinator.vote")

    async def deliver(self, shard: str, txn: str, decision: str) -> None:
        """Etapa 1. Envíalo una vez: `self.send(shard, {"type": decision, "txn": txn})`.
        Etapa 2. Una consolidación tiene que llegar: `await self.rpc(...)` y ante TimeoutError `await
        self.sleep(RETRY)` y vuelve a intentarlo, hasta que se confirme. Un aborto puede seguir yendo una vez."""
        raise NotImplementedError("PENDIENTE etapa 1: Coordinator.deliver")

    async def on_status(self, msg: Message) -> None:
        """Etapa 2. Un fragmento pregunta cómo terminó una transferencia. Responde
        {"type": "status_ok", "decision": d} donde d es self.log.read(txn); si es None y txn no está en
        self.active, d = "abort"."""
        raise NotImplementedError("PENDIENTE etapa 2: Coordinator.on_status")


class Shard(Node):
    """Un fragmento: aplica las escrituras de sus cuentas, a través de `self.db`."""

    def __init__(self, node_id: str, node_ids: list[str], db) -> None:
        super().__init__(node_id, node_ids)
        self.db = db

    async def recover(self) -> None:
        # Etapa 2: `self.every(ASK_EVERY, self.ask)`: las transferencias preparadas sobreviven a una caída
        #          (en disco, con sus bloqueos), y también aquellas cuya decisión se perdió por el camino.
        return

    async def on_write(self, msg: Message) -> None:
        ok = await self.db.write(msg.body["txn"], msg.body["account"], msg.body["delta"])
        self.reply(msg, {"type": "write_ok", "ok": ok})

    async def on_prepare(self, msg: Message) -> None:
        """Etapa 1. `vote = await self.db.prepare(txn, account, delta)`, y luego responde
        {"type": "prepare_ok", "vote": vote}."""
        raise NotImplementedError("PENDIENTE etapa 1: Shard.on_prepare")

    async def on_commit(self, msg: Message) -> None:
        """Etapa 1. `self.db.commit(txn)`, y luego responde {"type": "commit_ok"}."""
        raise NotImplementedError("PENDIENTE etapa 1: Shard.on_commit")

    async def on_abort(self, msg: Message) -> None:
        """Etapa 1. `self.db.abort(txn)`, y luego responde {"type": "abort_ok"}."""
        raise NotImplementedError("PENDIENTE etapa 1: Shard.on_abort")

    async def ask(self) -> None:
        """Etapa 2. Para cada txn de self.db.in_doubt() preparada hace al menos ASK_AFTER, averigua su
        resultado (`self.learn(txn)`, todas a la vez con asyncio.gather)."""
        raise NotImplementedError("PENDIENTE etapa 2: Shard.ask")

    async def learn(self, txn: str) -> None:
        """Etapa 2. `reply = await self.rpc(COORDINATOR, {"type": "status", "txn": txn}, timeout=RPC_TIMEOUT)`;
        consolida o aborta según diga la respuesta. Sin respuesta, o None: no hagas nada, mantén los
        bloqueos y vuelve a preguntar la próxima vez. Nunca abortes por tu cuenta: los demás pueden
        haber consolidado."""
        raise NotImplementedError("PENDIENTE etapa 2: Shard.learn")
