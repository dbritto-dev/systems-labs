"""Laboratorio broadcast: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Es el reto #3 de Gossip Glomers de Fly.io (https://fly.io/dist-sys/3a/), en Python.
Hay 25 nodos en una red donde cada mensaje tarda ~100 ms. Los clientes envían a cada nodo
`broadcast` (recuerda este número) y `read` (¿qué números tienes?). Cada número tiene que
llegar a cada nodo. Ahora mismo cada nodo solo guarda los números que le envían a él.

Haz las etapas en orden, en este archivo:

  Etapa 1  Varios nodos (3b): cuando un nodo aprende un número nuevo, se lo cuenta a sus
           vecinos.
  Etapa 2  Tolerante a fallos (3c): la red se parte de vez en cuando. Sigue reenviando
           hasta que el otro nodo diga que lo tiene (usa `await self.rpc(...)` y reintenta).
  Etapa 3  Eficiente (3d): menos de 30 mensajes por operación, latencia mediana por debajo
           de 400 ms y máxima por debajo de 600 ms.
  Etapa 4  Por lotes (3e): menos de 20 mensajes por operación: envía muchos números en un
           mensaje. Aquí puede ir más lento que en la etapa 3 (mediana por debajo de 1 s,
           máxima por debajo de 2 s).

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres, y todos los nodos ("n0" ... "n24")
  self.reply(msg, {...})           responde a una petición
  self.send(dest, {...})           envía sin esperar respuesta
  await self.rpc(dest, {...}, timeout=0.5)   envía y espera la respuesta (TimeoutError si se pierde)
  self.every(seconds, coroutine_function)    ejecuta algo de forma periódica

Guarda cada número que conozcas en `self.messages` (un set): el comprobador mira ahí.

Compruébalo:  LABS_LANG=es uv run pytest labs/broadcast
Mira una solución (¡después de intentarlo!):  labs/broadcast/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class BroadcastNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.messages: set[int] = set()
        self.neighbours: list[str] = []

    async def on_topology(self, msg: Message) -> None:
        """Los clientes envían a cada nodo sus vecinos en una cuadrícula, una vez, al empezar."""
        self.neighbours = msg.body["topology"][self.node_id]
        self.reply(msg, {"type": "topology_ok"})

    async def on_broadcast(self, msg: Message) -> None:
        self.messages.add(msg.body["message"])
        self.reply(msg, {"type": "broadcast_ok"})
        # Etapa 1: si el número es nuevo, envíalo a tus vecinos, por ejemplo con un
        # mensaje de un tipo propio: self.send(n, {"type": "gossip", "message": number}),
        # y atiéndelo en `async def on_gossip(self, msg)`.

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "messages": sorted(self.messages)})
