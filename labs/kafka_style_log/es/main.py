"""Laboratorio kafka_style_log: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Es el reto #5 de Gossip Glomers de Fly.io (https://fly.io/dist-sys/5a/), en Python.
Un log estilo Kafka: cada clave ("k0" ... "k9") es un log de mensajes, y cada mensaje recibe un
offset entero. Dos nodos atienden a los clientes, que hablan con cualquiera de los dos:

  send {key, msg}                       -> send_ok {offset}
  poll {offsets: {key: from}}           -> poll_ok {msgs: {key: [[offset, msg], ...]}}
  commit_offsets {offsets: {key: off}}  -> commit_offsets_ok
  list_committed_offsets {keys: [...]}  -> list_committed_offsets_ok {offsets: {key: off}}

Las reglas (el comprobador mira cada respuesta):
  - los offsets de una clave son únicos: dos mensajes nunca comparten uno;
  - ninguna escritura se pierde: un poll puede devolver cuantos mensajes quiera desde `from`,
    pero nunca saltarse un offset ya confirmado (ni devolver otro mensaje en él);
  - los offsets con commit nunca retroceden: listarlos devuelve al menos el último
    commit confirmado.

Ahora mismo cada nodo guarda su propio log: correcto con un nodo (reto 5a), incorrecto con dos.

Haz las etapas en orden, en este archivo:

  Etapa 1  Multinodo (5b): que los dos nodos se pongan de acuerdo. Tienes el `lin-kv`
           (linealizable) de Maelstrom: `kv = KV(self, "lin-kv")`, `await kv.read(k)`,
           `await kv.write(k, v)`, `await kv.cas(k, from_, to, create=True)` (RPCError con código
           20: la clave no existe; 22: alguien la cambió antes). Por ejemplo, un contador por clave
           para los offsets (CAS hasta que funcione), y cada mensaje guardado para que cualquier
           nodo pueda atender los polls.
  Etapa 2  Eficiente (5c): muchos menos mensajes por operación, y rápido aunque una clave reciba
           una avalancha o lin-kv vaya lento (muchos reintentos de CAS sobre un contador duelen).

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids         quién eres ("n0" o "n1"), y los dos nodos
  self.reply(msg, {...})              responde a una petición
  await self.rpc(dest, {...}, timeout=0.5)   pregunta a otro nodo (o a "lin-kv") y espera

Compruébalo:  LABS_LANG=es uv run pytest labs/kafka_style_log
Mira una solución (¡después de intentarlo!):  labs/kafka_style_log/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node


class KafkaNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.logs: dict[str, list[int]] = {}  # clave -> mensajes; el offset es el índice
        self.commits: dict[str, int] = {}

    async def on_send(self, msg: Message) -> None:
        log = self.logs.setdefault(msg.body["key"], [])
        log.append(msg.body["msg"])
        self.reply(msg, {"type": "send_ok", "offset": len(log) - 1})

    async def on_poll(self, msg: Message) -> None:
        out = {}
        for key, start in msg.body["offsets"].items():
            log = self.logs.get(key, [])
            out[key] = [[i, log[i]] for i in range(start, min(len(log), start + 10))]
        self.reply(msg, {"type": "poll_ok", "msgs": out})

    async def on_commit_offsets(self, msg: Message) -> None:
        for key, offset in msg.body["offsets"].items():
            self.commits[key] = max(offset, self.commits.get(key, -1))
        self.reply(msg, {"type": "commit_offsets_ok"})

    async def on_list_committed_offsets(self, msg: Message) -> None:
        offsets = {k: self.commits[k] for k in msg.body["keys"] if k in self.commits}
        self.reply(msg, {"type": "list_committed_offsets_ok", "offsets": offsets})
