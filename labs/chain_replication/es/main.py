"""Laboratorio chain_replication: TU ARCHIVO. Edítalo y guarda; la ventana en vivo lo vuelve a ejecutar.

Un almacén clave/valor guardado en 4 nodos (n0..n3) en una red donde cada mensaje tarda ~30 ms. Un
maestro de configuración (fiable, como ZooKeeper o etcd) guarda el orden de los nodos, la cabeza
primero, y le manda a cada nodo el orden nuevo cuando cambia (`self.chain`). Los clientes escriben
(`put`) en la cabeza, `self.chain[0]`, y leen (`get`) del nodo que elige `read_from(chain, rng)`.

Ahora mismo es primario-respaldo con replicación asíncrona: la cabeza (el primario) aplica una
escritura, responde enseguida y envía sus escrituras nuevas a los respaldos cada medio segundo. Las
lecturas se reparten entre todas las réplicas, así que a menudo no ven una escritura ya confirmada
(lecturas viejas); y cuando el primario se cae, se pierden las escrituras que confirmó y aún no había
enviado.

Haz las etapas en orden, en este archivo:

  Etapa 1  Una cadena. La cabeza numera cada escritura (`seq`) y se la pasa a su sucesor; cada nodo
           aplica las escrituras en orden y las pasa; la cola la aplica la última y responde al
           cliente, y manda un `ack` hacia arriba por la cadena, para que cada nodo olvide lo que
           guardaba. Lee de la cola: solo tiene escrituras que tienen todas las réplicas. Ni lecturas
           viejas ni escrituras perdidas; pero si cae un nodo, la cadena se atasca.
  Etapa 2  Reparación. En `chain_changed` (el maestro cambió la cadena):
           - eres la nueva cabeza: descarta las escrituras que guardabas esperando un hueco;
           - eres la nueva cola: responde a las escrituras que enviaste y nunca viste confirmadas;
           - tienes un sucesor nuevo: reenvíale cada escritura que enviaste y nunca viste confirmada.
           Un nodo que vuelve entra por la cola después de copiar el estado de la cola (dado,
           `on_join`): la cola debe guardar lo que aplica después de la copia, para reenviarlo.

Los mensajes (el maestro y los clientes mandan los suyos; tú mandas el resto):
  put {key, value}     -> la cola lo responde: self.answer(write)       (cliente -> cabeza)
  get {key}            -> get_ok {value}                                 (cliente -> read_from)
  write {seq, key, value, client, req}                                   (cadena abajo)
  ack {seq}            "todas las escrituras hasta seq están en la cola" (cadena arriba)
  config {chain}, join {tail}, snapshot -> snapshot_ok {store, seq}      (dados)

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.chain          quién eres, y la cadena (la cabeza primero)
  self.predecessor(), self.successor()   tus vecinos (None en los extremos)
  self.send(dest, {...})            envía sin esperar respuesta
  self.reply(msg, {...})            responde a una petición
  self.every(segundos, función_corrutina), self.spawn(corrutina), self.now()

Guarda los datos en `self.store`, como {clave: valor}: el verificador mira ahí.

Compruébalo:  uv run pytest labs/chain_replication
Mira una solución (¡después de intentarlo!):  labs/chain_replication/es/reference.py
"""

from __future__ import annotations

import random

from core.net import Message, Node

SHIP = 0.5  # etapa 0: el primario envía sus escrituras nuevas a los respaldos con esta frecuencia
SNAPSHOT_TIMEOUT = 3.0  # un nodo que entra espera esto como mucho a la copia de la cola


def read_from(chain: list[str], rng: random.Random) -> str:
    """De qué nodo lee un cliente (chain: la cabeza primero, la cola al final).

    Etapa 0 (dada): de cualquier réplica, para repartir la carga. Etapa 1: de la cola.
    """
    return rng.choice(chain)


class ChainNode(Node):
    """Una réplica.

    Contrato:
      - una escritura llega a cada nodo de la cadena, en el mismo orden, antes de responder a su cliente;
      - `get` responde desde `self.store`; `self.store[clave] = valor` es lo que guarda este nodo;
      - `chain_changed(old)` se ejecuta cada vez que el maestro manda una cadena nueva.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.chain: list[str] = []  # lo dice el maestro: la cabeza primero, la cola al final
        self.store: dict[str, int] = {}  # clave -> valor (el verificador mira aquí)
        self.seq = 0  # la última escritura aplicada aquí
        self.pending: dict[int, dict] = {}  # escrituras que llegaron antes de un hueco: seq -> escritura
        self.sent: dict[int, dict] = {}  # pasadas hacia abajo, aún sin confirmar por la cola: seq -> escritura
        self.copying = False  # como cola: un nodo copia nuestro estado (etapa 2)
        self.backlog: list[tuple] = []  # etapa 0: escrituras que el primario aún no ha enviado
        self.every(SHIP, self.ship)

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
        """Copia el estado de la cola; el maestro añade este nodo como la cola nueva cuando responde."""
        snap = await self.rpc(msg.body["tail"], {"type": "snapshot"}, timeout=SNAPSHOT_TIMEOUT)
        self.store, self.seq = dict(snap["store"]), snap["seq"]
        self.pending.clear()
        self.reply(msg, {"type": "join_ok"})

    async def on_snapshot(self, msg: Message) -> None:
        # Etapa 2: pon self.copying = True. Un nodo te está copiando; cuando el maestro lo haga tu
        # sucesor, necesitará cada escritura que apliques después de esta copia: `apply` las guarda en
        # self.sent.
        self.reply(msg, {"type": "snapshot_ok", "store": dict(self.store), "seq": self.seq})

    # ---- clientes

    async def on_get(self, msg: Message) -> None:
        self.reply(msg, {"type": "get_ok", "value": self.store.get(msg.body["key"])})

    async def on_put(self, msg: Message) -> None:
        """La escritura de un cliente, en la cabeza."""
        # Etapa 1: cambia todo esto por
        #     self.apply({"seq": self.seq + 1, "key": ..., "value": ..., "client": msg.src,
        #                 "req": msg.body["msg_id"]})
        # (la dirección del cliente y el id de su petición viajan con la escritura: la cola le responde).
        key, value = msg.body["key"], msg.body["value"]
        self.seq += 1
        self.store[key] = value
        self.backlog.append((self.seq, key, value))
        self.reply(msg, {"type": "put_ok"})  # confirmada antes de que la tenga ningún respaldo

    async def ship(self) -> None:
        """Etapa 0 (dada): el primario envía sus escrituras nuevas a los respaldos."""
        if self.backlog and self.predecessor() is None:
            items, self.backlog = self.backlog, []
            for backup in self.chain[1:]:
                self.send(backup, {"type": "replicate", "items": items})

    async def on_replicate(self, msg: Message) -> None:
        """Etapa 0 (dada): un respaldo aplica lo que envió el primario."""
        for seq, key, value in msg.body["items"]:
            if seq > self.seq:
                self.seq = seq
                self.store[key] = value

    # ---- la cadena

    async def on_write(self, msg: Message) -> None:
        """Etapa 1. Una escritura de tu predecesor: {"seq", "key", "value", "client", "req"}.

        Los mensajes pueden adelantarse unos a otros, y las escrituras se aplican en orden de seq:
        guárdala en self.pending[seq] y luego aplica (self.apply) mientras self.seq + 1 esté en
        self.pending. Ignora una escritura con seq <= self.seq: ya la tienes (la etapa 2 reenvía algunas).
        """
        raise NotImplementedError("TODO etapa 1: ChainNode.on_write")

    def apply(self, write: dict) -> None:
        """Etapa 1. Aplica una escritura (es la siguiente en orden) y pásala.

        self.store[key] = value y self.seq = seq. Luego:
          - con sucesor: guárdala en self.sent[seq] y mándale {"type": "write", **write};
          - en la cola: responde al cliente (self.answer(write)) y manda {"type": "ack", "seq": seq}
            a tu predecesor, si tienes.
        Etapa 2: en la cola, mientras self.copying, guárdala también en self.sent[seq].
        """
        raise NotImplementedError("TODO etapa 1: ChainNode.apply")

    async def on_ack(self, msg: Message) -> None:
        """Etapa 1. Todas las escrituras hasta msg.body["seq"] están en la cola: quítalas de self.sent
        y pasa el ack a tu predecesor, si tienes."""
        raise NotImplementedError("TODO etapa 1: ChainNode.on_ack")

    # ---- reparación

    async def chain_changed(self, old: list[str]) -> None:
        """Etapa 2. El maestro cambió la cadena: `old` era la de antes, `self.chain` es la de ahora.

        Busca tus vecinos viejos en `old` (ninguno si no estabas) y compáralos con
        self.predecessor() y self.successor():
          - sin predecesor ahora, con uno antes: eres la cabeza. self.pending.clear(): la cabeza vieja
            murió, el hueco que esperabas nunca llegará.
          - sin sucesor ahora, con uno antes: eres la cola. Responde a cada escritura de self.sent
            (en orden de seq), vacíalo y manda un ack de self.seq a tu predecesor.
          - con sucesor ahora, y distinto: reenvíale cada escritura de self.sent, en orden de seq
            (ignora las que ya tiene). Luego self.copying = False.
        """
        return
