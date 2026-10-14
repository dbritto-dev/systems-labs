"""Laboratorio failure_detection: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un clúster debe ponerse de acuerdo en quién está muerto, como lo hacen Cassandra, Akka, Consul y
Serf. 8 nodos en una red donde un mensaje tarda ~50 ms. Cada uno ejecuta tu `Detector` y guarda
`self.status`: lo que piensa de cada otro nodo, "alive" (vivo), "suspect" (sospechoso) o "dead"
(muerto). Un nodo sale del clúster (los clientes dejan de ir a él) en cuanto un nodo sano lo
declara muerto.

Ahora mismo cada nodo envía un latido a cada otro nodo cada HEARTBEAT segundos, y declara muerto
a un par tras TIMEOUT segundos sin ninguno. Pero cuatro enlaces de este clúster pasan por un switch
viejo que pierde la mitad de sus mensajes, así que se pierden cuatro latidos seguidos todo el
tiempo y se declaran muertos nodos sanos. Sube TIMEOUT a 3 s y eso se acaba, pero entonces un nodo
que de verdad se cayó se halla 3 s tarde, y sus clientes fallan todo ese tiempo.

Haz las etapas en orden, en este archivo:

  Etapa 1  Phi accrual: escribe `phi(intervals, elapsed)`, guarda los últimos WINDOW intervalos
           entre los latidos de cada par y juzga un silencio por su phi en vez de por un timeout
           fijo: sospechoso desde PHI_SUSPECT, muerto desde PHI_DEAD. Un par cuyos latidos llegan
           siempre a tiempo se halla rápido; uno tras un enlace que pierde recibe el tiempo que su
           historia pide.
  Etapa 2  SWIM: los latidos a todos cuestan 7 mensajes por nodo cada 0.25 s (28 por segundo, y
           crece con el clúster). En su lugar, cada PERIOD haz ping a UN par, dando la vuelta al
           anillo. ¿Sin ack en PING_TIMEOUT? Pide a K otros nodos que le hagan ping por ti (un
           `ping_req`): un enlace roto no es un nodo muerto. Nadie llegó: márcalo "suspect" y dale
           una última oportunidad (hazle ping y pregunta a todos los demás nodos, todo dentro de
           SUSPECT_TIMEOUT); si sigue sin nada: "dead". Cualquier mensaje de un par significa que
           está vivo.

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres, y todos los nodos ("n0" ... "n7")
  self.send(dest, {...})           envía sin esperar respuesta
  self.reply(msg, {...})           responde a una petición
  await self.rpc(dest, {...}, timeout=0.15)  envía y espera la respuesta (TimeoutError si no llega)
  self.every(seconds, coroutine_function)    ejecuta algo cada cierto tiempo
  self.spawn(coroutine)            ejecuta algo en segundo plano
  self.now()                       el reloj

El comprobador lee `self.status` (un dict: id del par -> "alive", "suspect" o "dead") cada 250 ms.

Compruébalo:  LABS_LANG=es uv run pytest labs/failure_detection
Mira una solución (¡después de intentarlo!):  labs/failure_detection/es/reference.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (etapa 2: asyncio.wait, asyncio.as_completed)
import math  # noqa: F401  (etapa 1: math.erfc, math.log10)
import random  # noqa: F401  (etapa 2: random.Random(node_id).sample para los ayudantes)
from collections import deque  # noqa: F401  (etapa 1: deque(maxlen=WINDOW))

from core.net import Message, Node, RPCError  # noqa: F401

ALIVE, SUSPECT, DEAD = "alive", "suspect", "dead"

# Etapas 0 y 1: latidos.
HEARTBEAT = 0.25  # segundos entre latidos a cada par
TIMEOUT = 1.0  # etapa 0: sin latido durante este tiempo -> muerto
WINDOW = 200  # etapa 1: intervalos guardados por par
MIN_STD = 0.05  # etapa 1: nunca te fíes de una dispersión menor que esta (segundos)
PHI_SUSPECT = 3.0  # etapa 1: sospecha de un par desde este phi ...
PHI_DEAD = 20.0  # ... y decláralo muerto desde este

# Etapa 2: SWIM.
PERIOD = 0.4  # segundos entre sondeos (un par por sondeo)
PING_TIMEOUT = 0.15  # espera esto a un ack (una ida y vuelta tarda ~0.1 s)
K = 3  # ayudantes a los que pedir que hagan ping a un par que no respondió
INDIRECT_TIMEOUT = 0.3  # espera esto a los ayudantes
SUSPECT_TIMEOUT = 0.8  # la última oportunidad de un sospechoso: este tiempo para responder a alguien


def phi(intervals: list[float], elapsed: float) -> float:
    """Etapa 1: lo sospechoso que es un silencio de `elapsed` segundos, dados los `intervals` pasados.

    Toma los intervalos como una distribución normal: su media y su desviación típica (al menos
    MIN_STD). phi = -log10(la probabilidad de que el próximo latido llegue aún más tarde que `elapsed`):
        later = 0.5 * math.erfc((elapsed - mean) / (std * math.sqrt(2)))
        phi = -math.log10(later)      (cuidado: later puede redondearse a 0.0; usa max(later, 1e-300))
    phi 1 = un 10% de que aún esté llegando, phi 3 = 0.1%, phi 20 = prácticamente ninguna.
    Sin intervalos todavía: devuelve 0.0.
    """
    raise NotImplementedError("PENDIENTE etapa 1: phi(intervals, elapsed)")


class Detector(Node):
    """Decide, para cada otro nodo, si está vivo.

    Contrato:
      - `self.status[peer]` es ALIVE, SUSPECT o DEAD, para cada otro nodo;
      - un par que se cayó debe pasar a DEAD en menos de 2.5 s;
      - un par sano nunca debe pasar a DEAD (puede estar SUSPECT un rato);
      - envía menos de 10 mensajes por segundo (este nodo, en media);
      - un nodo que vuelve de una caída debe estar ALIVE otra vez cuando sepas de él.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.peers = [n for n in node_ids if n != node_id]
        self.status = {p: ALIVE for p in self.peers}
        self.last_heard = {p: 0.0 for p in self.peers}
        # Etapa 1: self.intervals = {p: deque([HEARTBEAT], maxlen=WINDOW) for p in self.peers}
        # Etapa 2: sin latidos: self.every(PERIOD, ...) para sondear un par por periodo. Da la vuelta
        # al anillo empezando por el que va después de ti (n3 sondea n4, n5, n6, n7, n0, n1, n2, n4, ...):
        # como todos los nodos hacen lo mismo, alguien sondea cada nodo en cada PERIOD.
        self.every(HEARTBEAT, self.tick)

    async def tick(self) -> None:
        for p in self.peers:
            self.send(p, {"type": "heartbeat"})
        for p in self.peers:
            # Etapa 1: v = phi(list(self.intervals[p]), self.now() - self.last_heard[p]);
            # DEAD desde PHI_DEAD, SUSPECT desde PHI_SUSPECT (solo si estaba ALIVE).
            if self.now() - self.last_heard[p] > TIMEOUT:
                self.status[p] = DEAD

    async def on_heartbeat(self, msg: Message) -> None:
        # Etapa 1: primero añade a self.intervals[p] el intervalo desde el último latido
        # (siempre, incluso tras un silencio largo: así aprende phi un enlace que pierde mensajes).
        self.last_heard[msg.src] = self.now()
        self.status[msg.src] = ALIVE

    # ---- etapa 2: SWIM

    async def on_ping(self, msg: Message) -> None:
        """Etapa 2: un par nos hace ping: está vivo; responde {"type": "ack"}."""
        raise NotImplementedError("PENDIENTE etapa 2: on_ping")

    async def on_ping_req(self, msg: Message) -> None:
        """Etapa 2: haz ping a msg.body["target"] por el nodo que lo pidió (con msg.body["timeout"], si lo
        envió) y responde {"type": "ping_req_ok", "ok": True o False}."""
        raise NotImplementedError("PENDIENTE etapa 2: on_ping_req")

    async def reach(self, peer: str, direct: float, indirect: float, k: int = K) -> bool:
        """Etapa 2: ¿alguien llega a `peer`?

        Hazle ping; si no ha respondido en `direct` segundos, envía también un ping_req a `k` ayudantes
        al azar (que no sean `peer`) y dales a todos `indirect` segundos más. True en cuanto uno de ellos
        responda (un ack tardío a tu propio ping también cuenta).
        Pista: lanza el ping como tarea con asyncio.ensure_future, `await asyncio.wait([task],
        timeout=direct)`, luego añade una tarea por ayudante y recorre asyncio.as_completed(tasks).
        Cancela lo que quede al volver.

        Un sondeo es entonces: `reach(peer, PING_TIMEOUT, INDIRECT_TIMEOUT)`; si es False y el par estaba
        ALIVE: SUSPECT, luego `reach(peer, 0.0, SUSPECT_TIMEOUT, k=len(self.peers) - 1)`; si vuelve a ser
        False y sigue SUSPECT: DEAD.
        """
        raise NotImplementedError("PENDIENTE etapa 2: reach(peer, direct, indirect, k)")
