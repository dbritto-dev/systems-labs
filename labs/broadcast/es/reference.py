"""Laboratorio broadcast: una solución que funciona (etapas 4 y 5). Léela después de intentar es/main.py.

Un hub (n0) con lotes, y confirmaciones también agrupadas:

- Un nodo que recibe un número nuevo de un cliente se lo envía al hub enseguida.
- Cada 50 ms el hub envía un lote, con cada número nuevo desde el lote anterior, a cada
  nodo (también al de origen: recibir su propio número le dice que el hub ya lo tiene).
- Una vez por segundo cada nodo le dice al hub qué números recibió (un mensaje de confirmación, un ack), y
  le reenvía sus propios números que el hub aún no le ha devuelto. El hub le reenvía a un
  nodo lo que ese nodo no haya confirmado después de un segundo.

Disparar y olvidar en el camino rápido lo mantiene veloz (un salto de ida, hasta 50 ms, un
salto de vuelta: ~350 ms de mediana); el camino lento (confirmaciones y reenvíos) hace que aguante
las particiones. Unos 14 mensajes por operación a 20 operaciones/s.
"""

from __future__ import annotations

from core.net import Message, Node

BATCH = 0.05  # el hub envía un lote así de seguido (solo si tiene algo que enviar)
SYNC = 1.0  # confirmaciones y reenvíos así de seguido


class BroadcastNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.messages: set[int] = set()
        self.hub = node_ids[0]
        self.is_hub = node_id == self.hub
        if self.is_hub:
            self.fresh: set[int] = set()  # nuevos desde el último lote
            self.outstanding: dict[str, dict[int, float]] = {n: {} for n in node_ids if n != node_id}
            self.every(BATCH, self.send_batches)
        else:
            self.unconfirmed: dict[int, float] = {}  # números de mis clientes que el hub no ha devuelto
            self.received: set[int] = set()  # recibidos del hub desde mi última confirmación
            self.every(SYNC, self.sync)

    # ---- clientes

    async def on_topology(self, msg: Message) -> None:
        self.reply(msg, {"type": "topology_ok"})  # usamos nuestra propia topología: un hub

    async def on_broadcast(self, msg: Message) -> None:
        number = msg.body["message"]
        self.reply(msg, {"type": "broadcast_ok"})
        if number in self.messages:
            return
        self.messages.add(number)
        if self.is_hub:
            self.fresh.add(number)
        else:
            self.unconfirmed[number] = self.now()
            self.send(self.hub, {"type": "up", "messages": [number]})

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "messages": sorted(self.messages)})

    # ---- el hub

    async def on_up(self, msg: Message) -> None:
        new = set(msg.body["messages"]) - self.messages
        self.messages |= new
        self.fresh |= new

    async def send_batches(self) -> None:
        t = self.now()
        for dest, waiting in self.outstanding.items():
            for number in self.fresh:
                waiting.setdefault(number, t)
            due = [n for n, since in waiting.items() if n in self.fresh or t - since >= SYNC]
            if due:
                for n in due:
                    waiting[n] = t
                self.send(dest, {"type": "down", "messages": due})
        self.fresh = set()

    async def on_ack(self, msg: Message) -> None:
        waiting = self.outstanding[msg.src]
        for number in msg.body["messages"]:
            waiting.pop(number, None)

    # ---- los demás nodos

    async def on_down(self, msg: Message) -> None:
        numbers = msg.body["messages"]
        self.messages.update(numbers)
        self.received.update(numbers)
        for number in numbers:
            self.unconfirmed.pop(number, None)  # el hub lo tiene

    async def sync(self) -> None:
        if self.received:
            self.send(self.hub, {"type": "ack", "messages": sorted(self.received)})
            self.received = set()
        late = [n for n, since in self.unconfirmed.items() if self.now() - since >= SYNC]
        if late:
            self.send(self.hub, {"type": "up", "messages": late})
