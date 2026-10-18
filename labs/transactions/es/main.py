"""Laboratorio transactions: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Es el reto n.º 6 de Gossip Glomers de Fly.io (https://fly.io/dist-sys/6a/), en Python.
3 nodos guardan un almacén clave/valor; cada mensaje entre ellos tarda ~100 ms. Los clientes
envían a cualquier nodo una `txn`: una lista de microoperaciones, ["r", key, None] para leer y
["w", key, value] para escribir. El nodo responde `txn_ok` con la misma lista y cada lectura
rellenada. Cada valor escrito es único. De vez en cuando un nodo queda aislado de los demás
(una partición), pero los clientes siguen llegando a él: cada transacción debe seguir teniendo
respuesta (disponibilidad total).

Ahora mismo cada nodo tiene un almacén vacío y ningún manejador para `txn`, así que cada
transacción recibe un error.

Haz las etapas en orden, en este archivo:

  Etapa 1  Un solo nodo (6a): responde cada txn desde el almacén propio del nodo: ejecuta
           sus microoperaciones en orden, lecturas de self.store, escrituras en él, y
           responde {"type": "txn_ok", "txn": [...]} con cada lectura rellenada.
  Etapa 2  Replica (6b, sin particiones): envía cada escritura a los demás nodos, para
           que se pongan al día.
  Etapa 3  Read uncommitted (6b, con particiones): reenvía lo que el otro nodo no ha
           confirmado; cuando dos escrituras a una clave se cruzan, gana la más nueva en
           todas partes (sella cada transacción con (tiempo, nodo) y quédate con el sello mayor).
           Un sello para toda la transacción: las escrituras de dos transacciones nunca deben
           intercalarse, x de una e y de la otra (una "escritura sucia", G0).
  Etapa 4  Read committed (6c): que nadie vea nunca un valor que una transacción
           sobrescribió ella misma (una "lectura intermedia", G1b): replica transacciones
           enteras, solo con su valor final por clave, y aplica cada una de una vez. Read
           committed también prohíbe leer una escritura abortada (G1a: si abortas, con el
           código de error 30, sus escrituras deben desaparecer) y que dos transacciones lean
           cada una la escritura de la otra (G1c).

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres, y todos los nodos ("n0", "n1", "n2")
  self.reply(msg, {...})           responde a una petición
  self.send(dest, {...})           envía sin esperar respuesta
  await self.rpc(dest, {...}, timeout=0.5)   envía y espera la respuesta (TimeoutError si se pierde)
  self.every(seconds, coroutine_function), self.spawn(coroutine), self.now()

Guarda el valor actual de cada clave en `self.store` (un dict): el comprobador mira ahí.
No hagas `await` dentro de on_txn entre leer y escribir: un manejador que nunca espera se
ejecuta de una vez, así que nadie puede verlo a medias.

Compruébalo:  LABS_LANG=es uv run pytest labs/transactions
Mira una solución (¡después de intentarlo!):  labs/transactions/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class TxnNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[int, int] = {}

    # Etapa 1: añade
    #     async def on_txn(self, msg: Message) -> None:
    #         result = []
    #         for op, key, value in msg.body["txn"]:
    #             ...  # ["r", key, self.store.get(key)], o escribe self.store[key] = value
    #         self.reply(msg, {"type": "txn_ok", "txn": result})
    #
    # Etapa 2: envía las escrituras a los demás nodos (con un tipo de mensaje tuyo, por
    # ejemplo self.send(n, {"type": "replicate", "writes": [[key, value], ...]})), y
    # manéjalo en `async def on_replicate(self, msg)`.
