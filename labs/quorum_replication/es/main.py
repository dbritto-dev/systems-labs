"""Laboratorio quorum_replication: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Replicación sin líder, como la hacen Amazon Dynamo, Cassandra y Riak. 5 nodos en una red
donde cada mensaje tarda ~100 ms. Cada clave vive en 3 de ellos, sus réplicas
(`replicas_for(key, self.node_ids)`). Los clientes envían `put` y `get` a cualquier nodo sano,
y ese nodo coordina la petición. Ahora mismo un nodo solo guarda lo que le envían y responde
con su propia memoria, así que un `get` que cae en otro nodo no ve la última escritura.

Haz las etapas en orden, en este archivo:

  Etapa 1  Quórums: en `put`, envía el valor con una versión a las N=3 réplicas de la clave
           y responde cuando W=2 lo confirmaron; en `get`, pregunta a las réplicas y responde
           con la más nueva de R=2 respuestas. W + R > N, así que cada lectura se solapa con
           la última escritura, y un nodo puede estar caído sin que nadie lo note.
  Etapa 2  Reparación: un nodo que estuvo caído vuelve con datos viejos. Ponlo al día:
           guarda una "pista" (hint) por cada escritura que se perdió una réplica y entrégala
           cuando vuelva (hinted handoff), y arregla las réplicas atrasadas que veas al leer
           (read repair).

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres, y todos los nodos ("n0" ... "n4")
  self.reply(msg, {...})           responde a una petición
  self.send(dest, {...})           envía sin esperar respuesta
  await self.rpc(dest, {...}, timeout=0.5)   envía y espera la respuesta (TimeoutError si se pierde)
  self.every(seconds, coroutine_function)    ejecuta algo cada cierto tiempo
  self.spawn(coroutine)            ejecuta algo en segundo plano
  self.now()                       el reloj (aquí es el mismo en todos los nodos: sirve de versión)

Guarda tus datos en `self.store`, como {key: (version, value)}: el comprobador mira ahí.
Los clientes nunca escriben la misma clave dos veces a la vez.

Compruébalo:  LABS_LANG=es uv run pytest labs/quorum_replication
Mira una solución (¡después de intentarlo!):  labs/quorum_replication/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node

N, W, R = 3, 2, 2


def replicas_for(key: str, node_ids: list[str], n: int = N) -> list[str]:
    """Los n nodos que guardan `key`: su nodo de casa y los siguientes del anillo. (Dado: no lo cambies.)"""
    home = int(key[1:]) % len(node_ids)
    return [node_ids[(home + j) % len(node_ids)] for j in range(n)]


class QuorumNode(Node):
    """Coordina las peticiones de clientes que le llegan y guarda las claves de las que es réplica.

    Contrato:
      - `put` {key, value}  -> responde {"type": "put_ok"} cuando la escritura está a salvo;
      - `get` {key}         -> responde {"type": "get_ok", "value": value o None};
      - si no llegas a suficientes réplicas, responde {"type": "error", "code": 11};
      - `self.store[key] = (version, value)`: lo que guarda este nodo.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple] = {}

    async def on_put(self, msg: Message) -> None:
        # Etapa 1: version = (self.now(), self.node_id); envía {"type": "store", ...} a cada
        # réplica de replicas_for(key, self.node_ids) y responde put_ok tras W confirmaciones.
        # Pista: lanza una tarea por réplica (self.spawn o asyncio.ensure_future) y cuenta los
        # éxitos con asyncio.as_completed; un TimeoutError es una réplica que se la perdió.
        # Etapa 2: recuerda las escrituras que se perdió una réplica (una pista) y reenvíalas
        # cada medio segundo hasta que la réplica las confirme.
        key, value = msg.body["key"], msg.body["value"]
        self.store[key] = (self.now(), value)
        self.reply(msg, {"type": "put_ok"})

    async def on_get(self, msg: Message) -> None:
        # Etapa 1: pregunta a las réplicas ({"type": "fetch", "key": key}), espera R respuestas
        # y responde el valor con la versión más nueva.
        # Etapa 2 (read repair): envía la versión más nueva a las réplicas que respondieron con
        # una más vieja.
        entry = self.store.get(msg.body["key"])
        self.reply(msg, {"type": "get_ok", "value": entry[1] if entry else None})
