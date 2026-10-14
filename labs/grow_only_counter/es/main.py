"""Laboratorio grow_only_counter: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Es el reto n.º 4 de Gossip Glomers de Fly.io (https://fly.io/dist-sys/4/), en Python.
3 nodos reciben de los clientes `add` (un delta) y `read` (el total). La cuenta debe vivir
en el servicio `seq-kv` de Maelstrom, un almacén clave/valor *secuencialmente consistente*:
una lectura puede devolver un valor de hasta un segundo de antigüedad, aunque nunca más viejo
que lo que tú mismo escribiste. Ahora mismo cada nodo solo cuenta en memoria las sumas que le
llegan a él.

Haz las etapas en orden, en este archivo:

  Etapa 1  Cuenta compartida: guarda el total en una clave de seq-kv. Léela, suma y
           escríbela de vuelta.
  Etapa 2  Sin sumas perdidas: dos nodos pueden leer el mismo valor viejo y pisarse.
           Usa compare-and-swap (`cas`) y reintenta cuando falle.
  Etapa 3  Sin conflictos: en una sola clave caliente cada suma choca con todas las demás.
           Dale a cada nodo su propia clave, que solo él escribe, y lee la suma de todas.

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids        quién eres, y todos los nodos ("n0", "n1", "n2")
  self.reply(msg, {...})             responde a una petición
  kv = KV(self, "seq-kv")            y luego: await kv.read(key), await kv.write(key, value),
                                     await kv.cas(key, old, new, create=True)
  RPCError: e.code == 20 significa que la clave aún no existe, 22 que cas encontró otro valor.

Compruébalo:  LABS_LANG=es uv run pytest labs/grow_only_counter
Mira una solución (¡después de intentarlo!):  labs/grow_only_counter/es/reference.py
"""

from __future__ import annotations

from core.net import KV, Message, Node, RPCError  # noqa: F401  (KV y RPCError: para tus etapas)


class CounterNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.kv = KV(self, "seq-kv")
        self.count = 0  # Etapa 1: la cuenta debe vivir en seq-kv, no aquí

    async def on_add(self, msg: Message) -> None:
        # Etapa 1: lee la clave "counter" (una clave que no existe, RPCError código 20, cuenta
        #          como 0), suma msg.body["delta"], escríbela de vuelta y luego responde.
        # Etapa 2: en vez de write, cas(key, old, new, create=True); con el código 22 vuelve a
        #          leer y reintenta. Responde solo cuando haya funcionado.
        # Etapa 3: escribe solo tu propia clave (por ejemplo f"count-{self.node_id}"); eres su
        #          único escritor, así que lleva tu propio total y escríbelo (una escritura a la vez).
        self.count += msg.body["delta"]
        self.reply(msg, {"type": "add_ok"})

    async def on_read(self, msg: Message) -> None:
        # Etapa 1: lee "counter" de seq-kv. Etapa 3: lee la clave de cada nodo y súmalas.
        self.reply(msg, {"type": "read_ok", "value": self.count})
