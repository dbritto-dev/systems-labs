"""Laboratorio raft_consensus: TU ARCHIVO. Edítalo y guarda; la ventana en vivo lo vuelve a ejecutar.

5 nodos ("n0" ... "n4") en una red donde cada mensaje tarda ~20 ms. Los clientes envían
`{"type": "command", "value": 17}` al nodo que creen que lidera. Tu RaftNode debe acordar con
los demás un único log ordenado de comandos (Raft: https://raft.github.io/raft.pdf; la figura 2
es el algoritmo entero en una página). Ahora mismo nadie lidera nunca, así que todo comando falla.

Haz las etapas en orden, en este archivo:

  Etapa 1  Elección de líder: un seguidor que no oye a ningún líder durante un timeout de
           elección aleatorio se hace candidato: current_term += 1, se vota a sí mismo y envía
           RequestVote a los demás; una mayoría de votos lo hace líder, que entonces envía
           latidos (AppendEntries vacíos) para que los demás no se presenten. Un voto por
           nodo y término.
  Etapa 2  Replicación del log: el líder añade cada comando a su log y envía las entradas
           nuevas en AppendEntries (con prev_index y prev_term, para que un seguidor pueda decir
           "mi log no coincide ahí"). Responde `command_ok` al cliente solo cuando una mayoría
           (contando al líder) tiene la entrada: entonces está consolidada.
  Etapa 3  Seguridad: un líder aislado en una minoría no sabe que lo han depuesto. Cada
           respuesta y petición lleva el término: ante un término mayor, hazte seguidor;
           rechaza AppendEntries con un término menor; vota solo a un candidato cuyo log esté
           al menos igual de al día que el tuyo. Así nunca se pierde nada consolidado.

Los incidentes llegan al azar: el líder queda aislado con un seguidor, el host del líder se
cae (se reinicia después con current_term, voted_for y log: lo que Raft persiste), o la red
se vuelve lenta. El primero siempre aísla al líder entre 0:20 y 0:30.

El comprobador lee self.role, self.current_term y self.log de cada nodo (fuera de la red):
mantenlos al día. self.log es una lista de Entry(term, command).

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres, y todos los nodos
  self.reply(msg, {...})           responde a una petición
  await self.rpc(dest, {...}, timeout=0.25)  envía y espera la respuesta (TimeoutError si se pierde)
  self.spawn(corrutina)            la ejecuta en segundo plano (p. ej. un rpc por compañero)
  self.every(segundos, función_corrutina)    ejecuta algo periódicamente
  self.now()                       la hora, en segundos

Compruébalo:  LABS_LANG=es uv run pytest labs/raft_consensus
Mira una solución (¡después de intentarlo!):  labs/raft_consensus/es/reference.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from core.net import Message, Node

ELECTION_TIMEOUT = (0.3, 0.6)  # segundos sin líder antes de presentarse a una elección
HEARTBEAT = 0.1  # el líder envía AppendEntries al menos así de seguido
TICK = 0.05  # cada cuánto se ejecuta tick()
RPC_TIMEOUT = 0.25


@dataclass(frozen=True, slots=True)
class Entry:
    term: int
    command: int


class RaftNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        # Estado persistente: sobrevive a una caída (el escenario lo copia al nodo reiniciado).
        self.current_term = 0
        self.voted_for: str | None = None
        self.log: list[Entry] = []
        # Estado volátil.
        self.role = "follower"  # "follower", "candidate" o "leader"
        self.leader_id: str | None = None
        self.commit_index = 0  # cuántas entradas del log están consolidadas
        self.rng = random.Random(node_id)  # sus propios timeouts: los nodos no deben agotarlos a la vez
        self.peers = [n for n in node_ids if n != node_id]
        self.majority = len(node_ids) // 2 + 1
        self.deadline = self.now() + self.timeout()
        self.every(TICK, self.tick)

    def timeout(self) -> float:
        return self.rng.uniform(*ELECTION_TIMEOUT)

    async def tick(self) -> None:
        # Etapa 1: si lideras, envía un latido a cada compañero (al menos cada HEARTBEAT s).
        # Si no, cuando self.now() >= self.deadline, preséntate a una elección: sube el término,
        # vótate y lanza con self.spawn() un rpc RequestVote por compañero, p. ej.
        #   {"type": "request_vote", "term": ..., "candidate": self.node_id,
        #    "last_index": len(self.log), "last_term": término de tu última entrada o 0}
        # Con una mayoría de votos (el tuyo incluido), hazte líder.
        pass

    async def on_request_vote(self, msg: Message) -> None:
        # Etapa 1: concede el voto si el término es el actual y no has votado a otro en él
        # (recuerda self.voted_for), y retrasa tu propio plazo (self.deadline).
        # Etapa 3: ante un término mayor, hazte antes seguidor de él; y concede solo si el log
        # del candidato está al menos igual de al día: (last_term, last_index) >= los tuyos.
        self.reply(msg, {"type": "request_vote_ok", "term": self.current_term, "granted": False})

    async def on_append_entries(self, msg: Message) -> None:
        # Etapa 1: un latido del líder: síguelo (self.role, self.leader_id) y retrasa tu
        # plazo de elección (self.deadline).
        # Etapa 2: comprueba que tu log tiene prev_term en prev_index, borra las entradas que
        # choquen, añade las nuevas y sube self.commit_index hasta el del líder.
        # Etapa 3: recházalo (con tu término) si su término es menor que el tuyo.
        self.reply(msg, {"type": "append_entries_ok", "term": self.current_term, "success": False,
                         "match": len(self.log)})

    async def on_command(self, msg: Message) -> None:
        if self.role != "leader":  # el cliente prueba después con el líder que nombres
            self.reply(msg, {"type": "command_redirect", "leader": self.leader_id})
            return
        # Etapa 1: el líder responde enseguida (así se pierden comandos: arréglalo en la etapa 2).
        # Etapa 2: añade Entry(self.current_term, value) a self.log, replícala y responde
        # solo cuando una mayoría la tenga (guarda msg hasta entonces).
        self.reply(msg, {"type": "command_ok"})
