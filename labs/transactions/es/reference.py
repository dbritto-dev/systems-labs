"""Laboratorio transactions: una solución que funciona (etapa 3, read committed). Léela después de
intentar es/main.py.

Cada transacción recibe un sello (tiempo, rango del nodo, contador): un orden total en el que
coinciden todos los nodos. Un nodo ejecuta la transacción en su propio almacén de una vez
(nunca hace await dentro de on_txn), responde, y encola para cada uno de los demás nodos el
valor *final* de cada clave que escribió la transacción, con su sello. Cada 100 ms envía a cada
nodo un lote con lo que ese nodo aún no ha confirmado. Un nodo aplica un lote de una vez, clave
a clave quedándose con el sello mayor (gana la última escritura), y lo confirma.

- Read uncommitted (G0): todos los nodos ordenan las escrituras de una clave con los mismos sellos.
- Read committed (G1b): solo salen de un nodo los valores finales, y un lote se aplica de
  una vez, así que nadie ve nunca un valor que una transacción sobrescribió ella misma.
- Disponibilidad total: un nodo nunca espera a otro para responder a un cliente; una partición
  solo retrasa la replicación, y los lotes se reenvían hasta que los confirman.
"""

from __future__ import annotations

import itertools

from core.net import Message, Node

BATCH = 0.1  # envía las transacciones no confirmadas con esta frecuencia
TIMEOUT = 0.5


class TxnNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[int, int] = {}
        self.stamps: dict[int, tuple] = {}  # clave -> el sello de su valor actual
        self.rank = node_ids.index(node_id)
        self.counter = itertools.count()
        self.outbox: dict[str, dict[tuple, list]] = {n: {} for n in node_ids if n != node_id}
        self.every(BATCH, self.flush)

    def apply(self, stamp: tuple, writes: list) -> None:
        for key, value in writes:
            if stamp > self.stamps.get(key, ()):
                self.store[key] = value
                self.stamps[key] = stamp

    async def on_txn(self, msg: Message) -> None:
        stamp = (self.now(), self.rank, next(self.counter))
        result, final = [], {}
        for op, key, value in msg.body["txn"]:
            if op == "r":
                result.append(["r", key, self.store.get(key)])
            else:
                self.store[key] = value
                self.stamps[key] = stamp
                final[key] = value
                result.append(["w", key, value])
        self.reply(msg, {"type": "txn_ok", "txn": result})
        if final:
            for box in self.outbox.values():
                box[stamp] = list(final.items())

    async def flush(self) -> None:
        for dest, box in self.outbox.items():
            if box:
                self.spawn(self.send_batch(dest, dict(box)))

    async def send_batch(self, dest: str, batch: dict[tuple, list]) -> None:
        txns = [[list(stamp), writes] for stamp, writes in batch.items()]
        await self.rpc(dest, {"type": "replicate", "txns": txns}, timeout=TIMEOUT)
        for stamp in batch:  # confirmado
            self.outbox[dest].pop(stamp, None)

    async def on_replicate(self, msg: Message) -> None:
        for stamp, writes in sorted(msg.body["txns"]):
            self.apply(tuple(stamp), writes)
        self.reply(msg, {"type": "replicate_ok"})
