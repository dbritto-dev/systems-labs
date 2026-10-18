"""Laboratorio kafka_style_log: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Es el reto #5 de Gossip Glomers de Fly.io (https://fly.io/dist-sys/5a/), en Python.
Un log estilo Kafka: cada clave ("k0" ... "k9") es un log de mensajes, y cada mensaje recibe un
offset entero. Dos nodos atienden a los clientes, que hablan con cualquiera de los dos:

  send {key, msg}                       -> send_ok {offset}
  poll {offsets: {key: from}}           -> poll_ok {msgs: {key: [[offset, msg], ...]}}
  commit_offsets {offsets: {key: off}}  -> commit_offsets_ok
  list_committed_offsets {keys: [...]}  -> list_committed_offsets_ok {offsets: {key: off}}

Las reglas (el comprobador mira cada respuesta):
  - los offsets de una clave son únicos y siempre crecen: dos mensajes nunca comparten uno, un
    send nunca recibe un offset menor que uno ya confirmado, y un poll los da en orden;
  - ninguna escritura se pierde: un poll puede devolver cuantos mensajes quiera desde `from`,
    pero nunca saltarse un offset ya confirmado (ni devolver otro mensaje en él);
  - los offsets con commit nunca retroceden: listarlos devuelve al menos el último
    commit confirmado.

Ahora mismo el nodo no atiende ninguna de estas peticiones, así que cada una recibe un error.

Haz las etapas en orden, en este archivo:

  Etapa 1  Un solo nodo (5a): atiende las cuatro peticiones, cada nodo con su propio log en
           memoria: una lista de mensajes por clave (el offset es el índice) y el offset con
           commit de cada clave. Correcto con un nodo, incorrecto con dos (los dos dan el 0).
  Etapa 2  Multinodo (5b): que los dos nodos se pongan de acuerdo. Tienes los dos almacenes de
           Maelstrom: `lin-kv` (linealizable) y `seq-kv` (secuencialmente consistente: una
           lectura puede devolver un valor viejo, aquí de hasta 0,5 s). `kv = KV(self, "lin-kv")`
           o `KV(self, "seq-kv")`, y luego `await kv.read(k)`, `await kv.write(k, v)`,
           `await kv.cas(k, from_, to, create=True)` (RPCError con código 20: la clave no existe;
           22: alguien la cambió antes). Por ejemplo, un contador por clave para los offsets
           (CAS hasta que funcione), y cada mensaje guardado para que cualquier nodo pueda
           atender los polls.
           Fly.io te pide elegir qué datos necesitan lin-kv. Aquí un mensaje guardado una vez
           bajo su propia clave nunca cambia, así que una lectura vieja no puede mostrar otro
           anterior, y un contador con CAS se compara con el último valor (una lectura vieja
           solo cuesta un reintento): los dos pueden ir en seq-kv. Los commits no: el otro nodo
           puede leer un commit anterior, y un commit listado que retrocede es un commit
           perdido. Guárdalos en lin-kv.
  Etapa 3  Eficiente (5c): muchos menos mensajes por operación, y rápido aunque una clave reciba
           una avalancha o el almacén vaya lento (muchos reintentos de CAS sobre un contador
           duelen).

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids         quién eres ("n0" o "n1"), y los dos nodos
  self.reply(msg, {...})              responde a una petición
  await self.rpc(dest, {...}, timeout=0.5)   pregunta a otro nodo (o a un almacén) y espera

Compruébalo:  LABS_LANG=es uv run pytest labs/kafka_style_log
Mira una solución (¡después de intentarlo!):  labs/kafka_style_log/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class KafkaNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)

    # Etapa 1: guarda, en __init__,
    #     self.logs: dict[str, list[int]] = {}   # clave -> mensajes; el offset es el índice
    #     self.commits: dict[str, int] = {}      # clave -> offset con commit
    # y añade
    #     async def on_send(self, msg: Message) -> None:
    #         añade msg.body["msg"] al log de la clave, responde {"type": "send_ok", "offset": ...}
    #     async def on_poll(self, msg: Message) -> None:
    #         para cada clave y `from` de msg.body["offsets"], unos pocos pares [offset, msg]
    #         desde ahí: {"type": "poll_ok", "msgs": {clave: [[offset, msg], ...]}}
    #     async def on_commit_offsets(self, msg: Message) -> None:
    #         guarda el offset más alto de cada clave, responde {"type": "commit_offsets_ok"}
    #     async def on_list_committed_offsets(self, msg: Message) -> None:
    #         responde {"type": "list_committed_offsets_ok", "offsets": {clave: offset}} para
    #         las claves de msg.body["keys"] que tienen commit
    #
    # Etapa 2: guarda offsets, mensajes y commits en los almacenes (from core.net import KV,
    # RPCError), para que cualquier nodo pueda responder cualquier petición.
    #
    # Etapa 3: cuenta los viajes de un send. ¿Podría un nodo ser el dueño de cada clave?
