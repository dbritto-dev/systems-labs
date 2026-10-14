"""Laboratorio failure_detection: una solución que funciona (etapa 2). Léela después de intentar es/main.py.

Phi accrual (etapa 1): en vez de un único timeout para todos los pares, guarda los últimos intervalos
entre los latidos de un par y pregunta lo improbable que es el silencio actual, según ellos. Un par
cuyos latidos llegan siempre a tiempo se declara muerto enseguida; uno tras un enlace que pierde la
mitad de sus mensajes recibe el tiempo que su historia dice que necesita.

SWIM (etapa 2, lo que hace el Detector de abajo): se acabaron los latidos a todos. Cada PERIOD cada
nodo hace ping a UN par (dando la vuelta al anillo), así que un nodo envía unos pocos mensajes por
segundo, sea cual sea el tamaño del clúster. ¿Sin ack a tiempo? Pide a K otros nodos que le hagan ping
por nosotros (ping_req): un enlace roto entre dos nodos no es un nodo muerto. Nadie llegó: sospecha de
él y dale una última oportunidad paciente (SUSPECT_TIMEOUT) antes de declararlo muerto. Cualquier
mensaje de un par significa que está vivo.
"""

from __future__ import annotations

import asyncio
import math
import random

from core.net import Message, Node, RPCError

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

    Los intervalos se toman como una distribución normal (su media y su desviación típica, al menos
    MIN_STD); phi = -log10(la probabilidad de que el próximo latido llegue aún más tarde que `elapsed`).
    phi 1 = un 10% de que aún esté llegando, phi 3 = 0.1%, phi 20 = prácticamente ninguna.
    """
    if not intervals:
        return 0.0
    mean = sum(intervals) / len(intervals)
    var = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    std = max(math.sqrt(var), MIN_STD)
    later = 0.5 * math.erfc((elapsed - mean) / (std * math.sqrt(2)))
    return -math.log10(max(later, 1e-300))


class Detector(Node):
    """SWIM: sondea un par por periodo, de forma indirecta a través de K ayudantes, sospecha antes de matar."""

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.peers = [n for n in node_ids if n != node_id]
        self.status = {p: ALIVE for p in self.peers}
        self.rng = random.Random(node_id)
        me = node_ids.index(node_id)
        self.ring = node_ids[me + 1:] + node_ids[:me]  # los pares, empezando por el que va después de este nodo
        self.turn = 0
        self.checking: set[str] = set()  # sospechosos en su última oportunidad
        self.every(PERIOD, self.tick)

    def heard(self, peer: str) -> None:
        """Cualquier mensaje de un par: está vivo."""
        if peer in self.status:
            self.status[peer] = ALIVE

    async def on_ping(self, msg: Message) -> None:
        self.heard(msg.src)
        self.reply(msg, {"type": "ack"})

    async def on_ping_req(self, msg: Message) -> None:
        """Haz ping a `target` por el nodo que lo pidió, y dile si respondió."""
        self.heard(msg.src)
        target = msg.body["target"]
        ok = await self.ping(target, msg.body.get("timeout", PING_TIMEOUT))
        self.reply(msg, {"type": "ping_req_ok", "ok": ok})

    async def ping(self, peer: str, timeout: float) -> bool:
        try:
            await self.rpc(peer, {"type": "ping"}, timeout=timeout)
        except (TimeoutError, RPCError):
            return False
        self.heard(peer)
        return True

    async def ask(self, helper: str, peer: str, timeout: float) -> bool:
        try:
            body = {"type": "ping_req", "target": peer, "timeout": timeout * 0.6}  # deja tiempo para el relevo
            reply = await self.rpc(helper, body, timeout=timeout)
        except (TimeoutError, RPCError):
            return False
        self.heard(helper)
        if reply.get("ok"):
            self.heard(peer)
            return True
        return False

    async def reach(self, peer: str, direct: float, indirect: float, k: int = K) -> bool:
        """Haz ping a `peer`; si no ha respondido en `direct`, pide también a `k` ayudantes que lo intenten,
        y dales a todos `indirect` segundos más (un ack tardío también cuenta)."""
        tries = [asyncio.ensure_future(self.ping(peer, direct + indirect))]
        try:
            await asyncio.wait(tries, timeout=direct)
            if tries[0].done() and tries[0].result():
                return True
            helpers = self.rng.sample([p for p in self.peers if p != peer], k)
            tries += [asyncio.ensure_future(self.ask(h, peer, indirect)) for h in helpers]
            for done in asyncio.as_completed(tries):
                if await done:
                    return True
            return False
        finally:
            for t in tries:
                t.cancel()

    def next_target(self) -> str:
        """La vuelta al anillo, empezando por el nodo que va después de este: n3 sondea n4, n5, ..., n2.
        Como todos los nodos hacen lo mismo, alguien sondea cada nodo en cada PERIOD."""
        self.turn += 1
        return self.ring[(self.turn - 1) % len(self.ring)]

    async def tick(self) -> None:
        self.spawn(self.probe(self.next_target()))

    async def probe(self, peer: str) -> None:
        if self.status[peer] == DEAD:  # solo un ping, para notar cuándo vuelve
            await self.ping(peer, PING_TIMEOUT)
            return
        if await self.reach(peer, PING_TIMEOUT, INDIRECT_TIMEOUT):
            return
        if self.status[peer] == ALIVE and peer not in self.checking:
            self.status[peer] = SUSPECT
            self.checking.add(peer)
            try:
                alive = await self.reach(peer, 0.0, SUSPECT_TIMEOUT, k=len(self.peers) - 1)  # pregunta a todos
            finally:
                self.checking.discard(peer)
            if not alive and self.status[peer] == SUSPECT:
                self.status[peer] = DEAD
