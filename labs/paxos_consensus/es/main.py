"""Laboratorio paxos_consensus: TU ARCHIVO. Edítalo y guarda; la ventana en vivo lo vuelve a ejecutar.

5 nodos ("n0" ... "n4") llevan un log replicado de cambios de configuración: las posiciones 0, 1, 2, ...
guardan un comando cada una (un número). Los clientes envían `{"type": "command", "value": 17}` a
cualquier nodo; varios nodos proponen a la vez. Un nodo responde `command_ok` al cliente cuando el
comando está decidido en una posición y aplicado allí (learn() lo hace por ti). Todos los nodos deben
decidir el mismo valor en cada posición, y ningún comando confirmado al cliente puede desaparecer. Ahora
cada nodo se queda con el primer valor que oye para una posición, así que dos proponentes que compiten por
una posición parten el clúster: unos nodos deciden un comando y otros el otro.

Haz las etapas en orden, en este archivo:

  Etapa 1  Paxos de un solo valor por posición. Un proponente elige una boleta mayor que cualquiera que
           haya visto y envía `prepare`; un aceptador promete ignorar boletas menores y dice qué aceptó
           ya. Con una mayoría de promesas, el proponente debe proponer el valor aceptado con la boleta
           más alta (puede que ya esté elegido), y si no hay, el suyo, con `accept`. Una mayoría de
           aceptaciones lo decide. Es seguro, pero dos proponentes se superan uno al otro sin fin (se
           pisan), y cada comando cuesta dos idas y vueltas a todos.
  Etapa 2  Multi-Paxos con un líder estable. Un nodo que no oye a ningún líder durante un timeout
           aleatorio ejecuta la fase 1 una sola vez, para todas las posiciones desde su primera sin decidir
           (`campaign`); después lidera: cada comando es solo una ronda de `accept` (`phase2`), y los
           demás redirigen a los clientes hacia él. Un líder nuevo vuelve a proponer cada valor que le
           contaron las promesas, y llena cada posición vacía (una en la que nadie aceptó nada) con un
           no-op, o el log deja de aplicarse ahí.

Los incidentes llegan al azar: el líder se cae a mitad de una ronda, se cae otro nodo, la red pierde y
retrasa mensajes, una partición aísla al líder con un nodo, o el líder se detiene unos segundos (una
pausa del recolector de basura) y despierta seguro aún de que lidera. Un nodo caído se reinicia con
lo que Paxos guarda en disco: promised, accepted y decided. El primer incidente es siempre el líder
cayéndose mientras envía sus accept, a las 0:20 (vuelve a las 0:30).

El protocolo (el comprobador lee `decided`, `accepted` y `promised`; los dibujos leen los tipos):
  propose  {slot, value}                    etapa 0: gana el primero que un nodo oye para una posición
  prepare  {ballot, slot}  -> promise {ok, accepted: {slot: [ballot, value]} desde esa posición}
                                          o {ok: False, promised}
  accept   {ballot, slot, value} -> accepted {ok} o {ok: False, promised}
  decide   {slot, value}                    avisa a los demás (learn() lo guarda)
  heartbeat {ballot, upto}                  etapa 2: el líder está vivo; upto = su primera posición sin decidir
  command  {value} -> command_ok, o command_redirect {leader}    (cliente -> cualquier nodo)

Cómo habla tu nodo (mira core/net.py): self.node_id, self.node_ids, self.reply(msg, {...}),
self.send(dest, {...}), await self.rpc(dest, {...}, timeout), self.spawn(corrutina),
self.every(segundos, funcion_corrutina), self.now(); y las ayudas de abajo:
`await self.broadcast(body)` (a todos, tú incluido; las respuestas en cuanto contestó una mayoría),
`self.next_ballot(above)`, `self.learn(slot, value)`, `self.decide(slot, value)` (aprende y avisa a
los demás), `self.free_slot()`, `self.first_undecided()`, `self.accepted_from(slot)`.

Compruébalo:  uv run pytest labs/paxos_consensus
Mira una solución (¡después de intentarlo!):  labs/paxos_consensus/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.net import Message, Node, RPCError

NOOP = 0  # el valor que llena una posición vacía del log: no cambia nada al aplicarlo
TICK = 0.02  # cada cuánto se ejecuta tick()
HEARTBEAT = 0.15  # el líder envía algo a cada nodo al menos así de seguido
ELECTION_TIMEOUT = (0.3, 0.6)  # segundos sin oír a un líder antes de presentarse a la elección
RPC_TIMEOUT = 0.15  # segundos de espera de una respuesta antes de enviar otra vez
BACKOFF = 0.05  # etapa 1: un proponente superado espera hasta esto, el doble tras cada intento
GIVE_UP = 2.0  # etapa 1: un proponente deja de intentarlo con un comando tras esto (el cliente se fue)
SYNC_BATCH = 200  # posiciones decididas por respuesta de sync, como mucho


class PaxosNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        # En disco: sobrevive a una caída (el escenario lo copia en el nodo reiniciado).
        self.promised = 0  # la boleta más alta que este aceptador prometió (para todas las posiciones)
        self.accepted: dict[int, tuple[int, int]] = {}  # posición -> (boleta, valor) que aceptó
        self.decided: dict[int, int] = {}  # posición -> el valor decidido allí
        # En memoria: una caída lo pierde.
        self.applied = 0  # las posiciones 0 .. applied-1 están decididas y aplicadas, en orden
        self.waiting: dict[int, Message] = {}  # valor -> la petición del cliente a responder al aplicarlo
        self.busy: set[int] = set()  # posiciones para las que este nodo está proponiendo ahora
        self.proposing = asyncio.Lock()  # etapa 1: un nodo hace una ronda de Paxos a la vez
        self.highest = 0  # la boleta más alta que este nodo ha visto en cualquier parte
        self.role = "follower"  # "follower" (seguidor), "candidate" (candidato) o "leader" (líder)
        self.leader_id: str | None = None
        self.ballot = 0  # la boleta con la que este nodo se presenta o lidera
        self.next_slot = 0  # la siguiente posición libre del líder
        self.index = node_ids.index(node_id)
        self.majority = len(node_ids) // 2 + 1
        self.peers = [n for n in node_ids if n != node_id]
        self.rng = random.Random(node_id)  # sus propios timeouts: los nodos no deben vencer a la vez
        self.deadline = self.now() + self.timeout()
        self.last_sent: dict[str, float] = {}
        self.syncing = False
        self.every(TICK, self.tick)

    # ---- dado: el log, las boletas, hablar con todos

    def learn(self, slot: int, value: int) -> None:
        """Guarda un valor decidido, aplica el log en orden y responde a los clientes cuyo comando
        se acaba de aplicar aquí."""
        if slot in self.decided:
            return
        self.decided[slot] = value
        while self.applied in self.decided:
            msg = self.waiting.pop(self.decided[self.applied], None)
            if msg is not None:
                self.reply(msg, {"type": "command_ok", "slot": self.applied})
            self.applied += 1

    def first_undecided(self) -> int:
        """La posición más baja cuyo valor este nodo no conoce."""
        while self.applied in self.decided:
            self.applied += 1
        return self.applied

    def free_slot(self) -> int:
        """La posición sin decidir más baja para la que este nodo no está proponiendo ya."""
        slot = self.first_undecided()
        while slot in self.decided or slot in self.busy:
            slot += 1
        return slot

    def next_ballot(self, above: int) -> int:
        """La boleta más pequeña por encima de `above` que es de este nodo (boleta % 5 == su índice)."""
        n = len(self.node_ids)
        return (above // n + 1) * n + self.index

    def owner(self, ballot: int) -> str:
        return self.node_ids[ballot % len(self.node_ids)]

    def timeout(self) -> float:
        return self.rng.uniform(*ELECTION_TIMEOUT)

    def accepted_from(self, slot: int) -> dict[int, list[int]]:
        """Lo que este aceptador aceptó en cada posición desde `slot`: {posición: [boleta, valor]}."""
        return {s: [b, v] for s, (b, v) in self.accepted.items() if s >= slot}

    async def broadcast(self, body: dict, timeout: float = RPC_TIMEOUT) -> list[dict]:
        """Envía `body` a todos los nodos (este también) y devuelve las respuestas: en cuanto una
        mayoría dijo ok, o demasiados rechazaron para una mayoría, o tras `timeout`."""
        replies: list[dict] = []
        done = asyncio.get_running_loop().create_future()
        n = len(self.node_ids)

        async def one(node: str) -> None:
            try:
                reply = await self.rpc(node, body, timeout)
            except (TimeoutError, RPCError):
                return
            replies.append(reply)
            oks = sum(1 for r in replies if r.get("ok"))
            if not done.done() and (oks >= self.majority or len(replies) - oks > n - self.majority
                                    or len(replies) == n):
                done.set_result(None)

        for node in self.node_ids:
            self.spawn(one(node))
        try:
            async with asyncio.timeout(timeout):
                await done
        except TimeoutError:
            pass
        return list(replies)

    def count(self, replies: list[dict]) -> list[dict]:
        """Las respuestas ok; recuerda las boletas de los rechazos (mira `self.highest`)."""
        for r in replies:
            if not r.get("ok"):
                self.see(r.get("promised", 0))
        return [r for r in replies if r.get("ok")]

    def see(self, ballot: int) -> None:
        self.highest = max(self.highest, ballot)

    def decide(self, slot: int, value: int) -> None:
        """Una mayoría aceptó `value` en `slot`: apréndelo y avisa a los demás."""
        self.learn(slot, value)
        for peer in self.peers:
            self.send(peer, {"type": "decide", "slot": slot, "value": value})

    async def on_decide(self, msg: Message) -> None:
        self.learn(msg.body["slot"], msg.body["value"])

    async def on_sync(self, msg: Message) -> None:
        """Un nodo que va atrasado pide los valores decididos desde una posición."""
        start = msg.body["from"]
        top = self.first_undecided()
        decided = {s: self.decided[s] for s in range(start, min(top, start + SYNC_BATCH))}
        self.reply(msg, {"type": "sync_ok", "decided": decided})

    async def catch_up(self, node: str) -> None:
        """Pide a `node` los valores decididos que le faltan a este nodo."""
        if self.syncing:
            return
        self.syncing = True
        try:
            reply = await self.rpc(node, {"type": "sync", "from": self.first_undecided()}, RPC_TIMEOUT)
            for slot, value in reply["decided"].items():
                self.learn(slot, value)
        finally:
            self.syncing = False

    # ---- dado: seguir a un líder (la etapa 2 los llama)

    def follow(self, ballot: int, leader: str | None = None) -> None:
        """Alguien con `ballot` lidera: síguelo (y renuncia si supera a este nodo)."""
        self.see(ballot)
        if self.role != "follower" and ballot > self.ballot and self.owner(ballot) != self.node_id:
            self.step_down()
        if self.role == "follower":
            self.leader_id = leader or self.owner(ballot)
            self.deadline = self.now() + self.timeout()

    def preempted(self, promised: int) -> None:
        """Un aceptador rechazó la boleta de este nodo: prometió `promised`."""
        self.see(promised)
        if self.role != "follower" and promised > self.ballot:
            self.step_down()

    def step_down(self) -> None:
        self.role, self.leader_id = "follower", None
        self.waiting.clear()  # los clientes probarán con el líder nuevo
        self.deadline = self.now() + self.timeout()  # una espera aleatoria antes de presentarse otra vez

    async def on_preempt(self, msg: Message) -> None:
        self.preempted(msg.body["promised"])

    # ---- etapa 0 (dada): gana la primera propuesta que oye un nodo

    async def on_command(self, msg: Message) -> None:
        value = msg.body["value"]
        # Etapa 2: si self.role != "leader", responde {"type": "command_redirect", "leader": self.leader_id}
        #          y vuelve; si no, guárdalo en self.waiting, toma la posición self.next_slot (luego += 1) y
        #          self.spawn(self.phase2(slot, value)).
        self.waiting[value] = msg  # learn() lo responde cuando se aplica aquí
        # Etapa 1: cambia las líneas de abajo por `self.spawn(self.submit(value))`.
        slot = self.free_slot()
        self.busy.add(slot)
        for node in self.node_ids:
            self.send(node, {"type": "propose", "slot": slot, "value": value})

    async def on_propose(self, msg: Message) -> None:
        slot = msg.body["slot"]
        if slot not in self.decided:
            self.learn(slot, msg.body["value"])  # gana el primer valor que un nodo oye para una posición
        self.busy.discard(slot)

    # ---- el aceptador (etapa 1)

    async def on_prepare(self, msg: Message) -> None:
        """Etapa 1. Si msg.body["ballot"] > self.promised: promételo (self.promised = ballot) y
        responde {"type": "promise", "ok": True, "accepted": self.accepted_from(msg.body["slot"])}.
        Si no, responde {"type": "promise", "ok": False, "promised": self.promised}.

        Etapa 2: tras prometer, si no eres seguidor y la boleta es mayor que self.ballot, otro se
        presenta con una boleta más alta: self.step_down(). Y retrasa self.deadline
        (self.now() + self.timeout()) para dar tiempo al candidato a ganar."""
        raise NotImplementedError("PENDIENTE etapa 1: PaxosNode.on_prepare")

    async def on_accept(self, msg: Message) -> None:
        """Etapa 1. Si msg.body["ballot"] >= self.promised: self.promised = ballot,
        self.accepted[slot] = (ballot, value), responde {"type": "accepted", "ok": True}.
        Si no, responde {"type": "accepted", "ok": False, "promised": self.promised}.

        Etapa 2: cuando aceptas, el líder está vivo: self.follow(ballot)."""
        raise NotImplementedError("PENDIENTE etapa 1: PaxosNode.on_accept")

    # ---- el proponente (etapa 1): una ronda completa de Paxos por posición

    async def submit(self, value: int) -> None:
        """Etapa 1. Propón `value` posición tras posición hasta que se elija en una. Mantén
        `async with self.proposing:` (una ronda a la vez por nodo) y, mientras value siga en
        self.waiting (learn() lo saca al aplicarlo) y durante GIVE_UP segundos como mucho: toma
        slot = self.free_slot(), añádelo a self.busy mientras ejecutas `chosen = await self.paxos(slot,
        value)` (quítalo después), y para cuando chosen == value. Otro valor: ya estaba elegido ahí,
        sigue. None (te superó una boleta más alta): duerme antes un tiempo aleatorio
        self.rng.uniform(0, BACKOFF * 2 ** tries) (tries hasta 4), o los proponentes se siguen
        superando unos a otros."""
        raise NotImplementedError("PENDIENTE etapa 1: PaxosNode.submit")

    async def paxos(self, slot: int, value: int) -> int | None:
        """Etapa 1. Paxos de un solo valor para una posición; devuelve el valor elegido ahí, o None.
          1. ballot = self.next_ballot(max(self.promised, self.highest)); self.see(ballot).
          2. oks = self.count(await self.broadcast({"type": "prepare", "ballot": ballot, "slot": slot}));
             menos de self.majority: devuelve None.
          3. Si alguna respuesta ok trae r["accepted"][slot], propón el valor de la que tenga la boleta
             más alta en vez del tuyo (puede que ya esté elegido: no lo sobrescribas nunca).
          4. Lo mismo con {"type": "accept", "ballot": ballot, "slot": slot, "value": value}; con una
             mayoría de oks, self.decide(slot, value) y devuelve value; si no, None.
        """
        raise NotImplementedError("PENDIENTE etapa 1: PaxosNode.paxos")

    # ---- Multi-Paxos (etapa 2): un líder, la fase 1 una vez para todas las posiciones

    async def tick(self) -> None:
        # Etapa 2: un líder envía {"type": "heartbeat", "ballot": self.ballot, "upto": self.first_undecided()}
        # a cada par al que no envió nada en HEARTBEAT segundos (self.last_sent[peer]). Un seguidor
        # cuyo self.deadline ya pasó se presenta a la elección: self.spawn(self.campaign()).
        return

    async def campaign(self) -> None:
        """Etapa 2. La fase 1 una sola vez, para todas las posiciones desde start = self.first_undecided().
          - ballot = self.next_ballot(max(self.promised, self.highest)); self.see(ballot);
            self.role, self.ballot, self.leader_id = "candidate", ballot, None; retrasa self.deadline
            un self.timeout() aleatorio (la espera si este intento falla: presentarse otra vez al
            instante, o tras una espera fija, hace que los candidatos se pisen sin fin).
          - oks = self.count(await self.broadcast({"type": "prepare", "ballot": ballot, "slot": start})).
            Si ya no eres el candidato, o tienes menos de self.majority oks, o
            self.highest > ballot: vuelve a ser seguidor y sal.
          - Lidera: self.role, self.leader_id = "leader", self.node_id.
          - Para cada posición desde start hasta la más alta que contó alguna promesa, salvo las que sabes
            decididas: self.spawn(self.phase2(slot, v)) donde v es el valor con la boleta más alta que
            contaron las promesas ahí, o NOOP si ninguna lo hizo (una posición vacía).
            self.next_slot = esa más alta + 1.
        """
        raise NotImplementedError("PENDIENTE etapa 2: PaxosNode.campaign")

    async def phase2(self, slot: int, value: int) -> None:
        """Etapa 2. Aceptar y luego decidir, sin preparar: la boleta del líder vale para todas las
        posiciones. A cada nodo (lanza un emisor por nodo), mientras sigas liderando con esa boleta y la
        posición no esté decidida: self.last_sent[node] = self.now(); rpc {"type": "accept", "ballot":
        self.ballot, "slot": slot, "value": value} con RPC_TIMEOUT; si salta TimeoutError, envíalo
        otra vez; un rechazo (ok False) es self.preempted(reply["promised"]). Cuando una mayoría
        aceptó: self.decide(slot, value)."""
        raise NotImplementedError("PENDIENTE etapa 2: PaxosNode.phase2")

    async def on_heartbeat(self, msg: Message) -> None:
        """Etapa 2. Si msg.body["ballot"] < self.promised, al emisor lo depusieron y no lo sabe:
        self.send(msg.src, {"type": "preempt", "promised": self.promised}) y sal. Si no,
        self.follow(ballot, msg.src); y si msg.body["upto"] > self.first_undecided(), te perdiste
        decisiones: self.spawn(self.catch_up(msg.src))."""
        raise NotImplementedError("PENDIENTE etapa 2: PaxosNode.on_heartbeat")
