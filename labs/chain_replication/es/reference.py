"""Laboratorio chain_replication: una solución que funciona (etapa 2). Léela después de intentar main.py.

Una cadena: la cabeza numera cada escritura y la pasa hacia abajo; cada nodo aplica las escrituras en
orden y las pasa; la cola la aplica la última y responde al cliente, y su confirmación sube de vuelta
por la cadena para que cada nodo pueda olvidarla. Las lecturas van a la cola: solo tiene escrituras
que están en todas las réplicas, así que una lectura nunca ve un valor que aún se pueda perder, ni
deja de ver uno confirmado.

Reparación, cuando el maestro cambia la cadena:
  - murió la cabeza: el siguiente nodo es la cabeza. Las escrituras que esperaban un hueco de la
    cabeza vieja nunca llegarán.
  - murió la cola: su predecesor es la cola. Responde a las escrituras que envió y nunca vio confirmadas.
  - murió un nodo en medio: su predecesor reenvía a su nuevo sucesor lo que envió y nunca vio
    confirmado (el sucesor descarta lo que ya tiene).
  - entra un nodo: copia el estado de la cola; la cola guarda lo que aplica después de la copia y se
    lo reenvía cuando el nodo es su sucesor (el mismo reenvío que al reparar un nodo en medio).
"""

from __future__ import annotations

import random

from core.net import Message, Node

SHIP = 0.5  # etapa 0: el primario envía sus escrituras nuevas a los respaldos con esta frecuencia
SNAPSHOT_TIMEOUT = 3.0  # un nodo que entra espera esto como mucho a la copia de la cola


def read_from(chain: list[str], rng: random.Random) -> str:
    """De qué nodo lee un cliente: la cola, la única que no tiene nada sin confirmar."""
    return chain[-1]


class ChainNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.chain: list[str] = []  # lo dice el maestro: la cabeza primero, la cola al final
        self.store: dict[str, int] = {}  # clave -> valor (el comprobador mira aquí)
        self.seq = 0  # la última escritura aplicada aquí
        self.pending: dict[int, dict] = {}  # escrituras que llegaron antes de un hueco: seq -> escritura
        self.sent: dict[int, dict] = {}  # pasadas hacia abajo, aún sin confirmar por la cola: seq -> escritura
        self.copying = False  # como cola: un nodo copia nuestro estado, guarda en sent lo que apliquemos

    # ---- dónde estamos en la cadena (dado)

    def predecessor(self) -> str | None:
        if self.node_id not in self.chain:
            return None
        i = self.chain.index(self.node_id)
        return self.chain[i - 1] if i > 0 else None

    def successor(self) -> str | None:
        if self.node_id not in self.chain:
            return None
        i = self.chain.index(self.node_id)
        return self.chain[i + 1] if i + 1 < len(self.chain) else None

    def answer(self, write: dict) -> None:
        """Dile al cliente que su escritura está hecha (dado). Un cliente ignora una segunda respuesta."""
        self.send(write["client"], {"type": "put_ok", "in_reply_to": write["req"]})

    # ---- el maestro (dado)

    async def on_config(self, msg: Message) -> None:
        old, self.chain = self.chain, list(msg.body["chain"])
        await self.chain_changed(old)
        self.reply(msg, {"type": "config_ok"})

    async def on_join(self, msg: Message) -> None:
        snap = await self.rpc(msg.body["tail"], {"type": "snapshot"}, timeout=SNAPSHOT_TIMEOUT)
        self.store, self.seq = dict(snap["store"]), snap["seq"]
        self.pending.clear()
        self.reply(msg, {"type": "join_ok"})

    async def on_snapshot(self, msg: Message) -> None:
        self.copying = True  # lo que apliquemos desde ahora lo necesitará el nodo nuevo
        self.reply(msg, {"type": "snapshot_ok", "store": dict(self.store), "seq": self.seq})

    # ---- clientes

    async def on_get(self, msg: Message) -> None:
        self.reply(msg, {"type": "get_ok", "value": self.store.get(msg.body["key"])})

    async def on_put(self, msg: Message) -> None:
        """En la cabeza: numera la escritura y échala a andar por la cadena."""
        self.apply({"seq": self.seq + 1, "key": msg.body["key"], "value": msg.body["value"],
                    "client": msg.src, "req": msg.body["msg_id"]})

    # ---- la cadena

    async def on_write(self, msg: Message) -> None:
        write = {k: msg.body[k] for k in ("seq", "key", "value", "client", "req")}
        if write["seq"] <= self.seq:
            return  # un reenvío de algo que ya tenemos
        self.pending[write["seq"]] = write
        while self.seq + 1 in self.pending:
            self.apply(self.pending.pop(self.seq + 1))

    def apply(self, write: dict) -> None:
        self.store[write["key"]] = write["value"]
        self.seq = write["seq"]
        succ = self.successor()
        if succ is None:  # la cola: hecho
            self.answer(write)
            if self.copying:
                self.sent[write["seq"]] = write
            pred = self.predecessor()
            if pred is not None:
                self.send(pred, {"type": "ack", "seq": write["seq"]})
        else:
            self.sent[write["seq"]] = write
            self.send(succ, {"type": "write", **write})

    async def on_ack(self, msg: Message) -> None:
        seq = msg.body["seq"]
        for s in [s for s in self.sent if s <= seq]:
            del self.sent[s]
        pred = self.predecessor()
        if pred is not None:
            self.send(pred, {"type": "ack", "seq": seq})

    # ---- reparación

    async def chain_changed(self, old: list[str]) -> None:
        if self.node_id not in self.chain:
            return
        mine = old.index(self.node_id) if self.node_id in old else None
        old_pred = old[mine - 1] if mine is not None and mine > 0 else None
        old_succ = old[mine + 1] if mine is not None and mine + 1 < len(old) else None
        pred, succ = self.predecessor(), self.successor()
        if pred is None and old_pred is not None:  # ahora somos la cabeza
            self.pending.clear()  # la cabeza vieja nunca llenará el hueco
        if succ is None and old_succ is not None:  # ahora somos la cola
            for seq in sorted(self.sent):
                self.answer(self.sent[seq])
            self.sent.clear()
            if pred is not None:
                self.send(pred, {"type": "ack", "seq": self.seq})
        elif succ is not None and succ != old_succ:  # un sucesor nuevo: reenvíale lo que le pueda faltar
            for seq in sorted(self.sent):
                self.send(succ, {"type": "write", **self.sent[seq]})
            self.copying = False
