"""Laboratorio g_counter: una solución que funciona (etapa 3). Léela después de intentar es/main.py.

Cada nodo tiene una clave de seq-kv, `count-<id del nodo>`, y es el único que la escribe.
Así no hay nada por lo que pelear: ni compare-and-swap ni reintentos. El nodo lleva su propio
total en memoria y lo escribe por tandas, una escritura a la vez (para que nunca lleguen
desordenadas), y confirma una suma cuando ha funcionado una escritura que la incluye.

Una lectura suma la clave de cada nodo. Tu propia clave siempre está al día (seq-kv te enseña
tus propias escrituras); las demás pueden tener hasta un segundo de retraso, algo que este
reto permite: el contador solo tiene que acabar cuadrando.
"""

from __future__ import annotations

import asyncio

from core.net import KV, Message, Node, RPCError

FLUSH = 0.05  # segundos entre escrituras de nuestro total


class CounterNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.kv = KV(self, "seq-kv")
        self.mine = 0  # todo lo sumado a través de este nodo
        self.written = 0  # lo que seq-kv tiene en nuestra clave
        self.waiting: list[tuple[int, Message]] = []  # (total que la incluye, petición)
        self.writing = False  # una escritura a la vez, para que nunca lleguen desordenadas
        self.every(FLUSH, self.flush)

    @staticmethod
    def key(node_id: str) -> str:
        return f"count-{node_id}"

    async def on_add(self, msg: Message) -> None:
        self.mine += msg.body["delta"]
        self.waiting.append((self.mine, msg))

    async def flush(self) -> None:
        if self.mine != self.written and not self.writing:
            self.writing = True
            self.spawn(self.write(self.mine))

    async def write(self, total: int) -> None:
        try:
            await self.kv.write(self.key(self.node_id), total)
        finally:
            self.writing = False  # hecha, o sin respuesta a tiempo: la próxima tanda lo reintenta
        self.written = total
        done = [m for t, m in self.waiting if t <= total]
        self.waiting = [(t, m) for t, m in self.waiting if t > total]
        for m in done:
            self.reply(m, {"type": "add_ok"})

    async def read_key(self, node_id: str) -> int:
        try:
            return await self.kv.read(self.key(node_id))
        except RPCError as e:
            if e.code == 20:  # ese nodo aún no ha contado nada
                return 0
            raise

    async def on_read(self, msg: Message) -> None:
        values = await asyncio.gather(*(self.read_key(n) for n in self.node_ids))
        self.reply(msg, {"type": "read_ok", "value": sum(values)})
