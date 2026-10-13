"""Laboratorio unique_ids: una solución que funciona (etapa 3). Léela después de intentar es/main.py.

IDs Snowflake, como los de Twitter: un entero de 63 bits hecho de

    milisegundos desde una época propia (41 bits) | número de nodo (10 bits) | secuencia (12 bits)

Únicos sin preguntar a nadie: el número de nodo hace que los IDs de dos nodos difieran, y la
secuencia hace que difieran los IDs del mismo nodo en el mismo milisegundo. Ordenados por
tiempo porque los milisegundos van primero.

El reloj puede saltar atrás (NTP, una pausa de la VM). Entonces seguimos usando la última
marca de tiempo que usamos y seguimos contando la secuencia (tomando prestado el siguiente
milisegundo cuando se agota), así los IDs nunca se repiten ni van hacia atrás.
"""

from __future__ import annotations

from core.net import Message, Node

EPOCH_MS = 1_735_689_600_000  # 2025-01-01: 41 bits de milisegundos duran ~69 años desde aquí
NODE_BITS, SEQ_BITS = 10, 12
MAX_SEQ = (1 << SEQ_BITS) - 1


class UniqueIdNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.number = int(node_id.removeprefix("n"))
        self.last_ms = -1
        self.seq = 0

    async def on_echo(self, msg: Message) -> None:
        self.reply(msg, {"type": "echo_ok", "echo": msg.body["echo"]})

    async def on_generate(self, msg: Message) -> None:
        self.reply(msg, {"type": "generate_ok", "id": self.next_id()})

    def next_id(self) -> int:
        ms = max(self.wall_ms() - EPOCH_MS, self.last_ms)  # no retroceder nunca con el reloj
        if ms == self.last_ms:
            self.seq += 1
            if self.seq > MAX_SEQ:  # gastado este milisegundo: toma prestado el siguiente
                ms, self.seq = ms + 1, 0
        else:
            self.seq = 0
        self.last_ms = ms
        return (ms << (NODE_BITS + SEQ_BITS)) | (self.number << SEQ_BITS) | self.seq
