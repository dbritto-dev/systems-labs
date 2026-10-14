"""Laboratorio unique_id_generation: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los retos #1 y #2 de Gossip Glomers de Fly.io (https://fly.io/dist-sys/1/ y /2/), en
Python. 5 nodos, ~100 ms por mensaje. Los clientes envían a cada nodo peticiones `echo` y
`generate`. Ahora mismo el nodo no atiende ninguna de las dos, así que cada petición
recibe un error.

Haz las etapas en orden, en este archivo:

  Etapa 1  Echo (#1): responde a {"type": "echo", "echo": X} con {"type": "echo_ok", "echo": X}.
  Etapa 2  IDs únicos (#2): responde a {"type": "generate"} con {"type": "generate_ok", "id": ...},
           un ID que ninguna otra petición haya recibido, desde ningún nodo. Tiene que seguir
           funcionando mientras la red entre los nodos está partida (los clientes siguen
           llegando a todos los nodos), así que preguntar a otro nodo no es una opción.
  Etapa 3  IDs de 64 bits ordenables: que el ID sea un entero entre 0 y 2**63 - 1 (cabe en un
           bigint de base de datos) que crece con el tiempo, para que ordenar los IDs los
           ordene por creación (Snowflake: milisegundos | nodo | secuencia). Cuidado: los
           relojes pueden saltar HACIA ATRÁS.

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres ("n0" ... "n4") y todos los nodos
  self.reply(msg, {...})           responde a una petición
  await self.rpc(dest, {...})      pregunta a otro nodo y espera (falla durante una partición)
  self.wall_ms()                   el reloj de pared de este nodo, en milisegundos desde 1970
                                   (puede saltar atrás cuando NTP lo corrige)

Compruébalo:  LABS_LANG=es uv run pytest labs/unique_id_generation
Mira una solución (¡después de intentarlo!):  labs/unique_id_generation/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class UniqueIdNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)

    # Etapa 1: añade
    #     async def on_echo(self, msg: Message) -> None:
    #         self.reply(msg, {"type": "echo_ok", "echo": msg.body["echo"]})
    #
    # Etapa 2: añade `async def on_generate(self, msg: Message)` que responda
    #     {"type": "generate_ok", "id": <único>}
    # Pista: ¿qué es único de este nodo, y qué es único de esta petición en este nodo?
    #
    # Etapa 3: construye el ID con self.wall_ms(), el número del nodo y una secuencia,
    # y no dejes nunca que la marca de tiempo que usas vaya hacia atrás.
