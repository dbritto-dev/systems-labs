"""Laboratorio paxos_consensus: una solución que funciona (todas las etapas). Léela después de intentar main.py."""

from __future__ import annotations

import asyncio
import random

from core.net import Message, Node, RPCError

NOOP = 0  # el valor que llena un hueco vacío del log: no cambia nada al aplicarlo
TICK = 0.02  # cada cuánto se ejecuta tick()
HEARTBEAT = 0.15  # el líder envía algo a cada nodo al menos así de seguido
ELECTION_TIMEOUT = (0.3, 0.6)  # segundos sin oír a un líder antes de presentarse a la elección
RPC_TIMEOUT = 0.15  # segundos de espera de una respuesta antes de enviar otra vez
BACKOFF = 0.05  # etapa 1: un proponente superado espera hasta esto, el doble tras cada intento
GIVE_UP = 2.0  # etapa 1: un proponente deja de intentarlo con un comando tras esto (el cliente se fue)
SYNC_BATCH = 200  # huecos decididos por respuesta de sync, como mucho


class PaxosNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        # En disco: sobrevive a una caída (el escenario lo copia en el nodo reiniciado).
        self.promised = 0  # la boleta más alta que este aceptador prometió (para todos los huecos)
        self.accepted: dict[int, tuple[int, int]] = {}  # hueco -> (boleta, valor) que aceptó
        self.decided: dict[int, int] = {}  # hueco -> el valor decidido allí
        # En memoria: una caída lo pierde.
        self.applied = 0  # los huecos 0 .. applied-1 están decididos y aplicados, en orden
        self.waiting: dict[int, Message] = {}  # valor -> la petición del cliente a responder al aplicarlo
        self.busy: set[int] = set()  # huecos para los que este nodo está proponiendo ahora
        self.proposing = asyncio.Lock()  # etapa 1: un nodo hace una ronda de Paxos a la vez
        self.highest = 0  # la boleta más alta que este nodo ha visto en cualquier parte
        self.role = "follower"  # "follower" (seguidor), "candidate" (candidato) o "leader" (líder)
        self.leader_id: str | None = None
        self.ballot = 0  # la boleta con la que este nodo se presenta o lidera
        self.next_slot = 0  # el siguiente hueco libre del líder
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
        """El hueco más bajo cuyo valor este nodo no conoce."""
        while self.applied in self.decided:
            self.applied += 1
        return self.applied

    def free_slot(self) -> int:
        """El hueco sin decidir más bajo para el que este nodo no está proponiendo ya."""
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
        """Lo que este aceptador aceptó en cada hueco desde `slot`: {hueco: [boleta, valor]}."""
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
        """Un nodo que va atrasado pide los valores decididos desde un hueco."""
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

    # ---- clientes (etapa 2: solo el líder propone; los demás redirigen)

    async def on_command(self, msg: Message) -> None:
        value = msg.body["value"]
        if self.role != "leader":  # el cliente prueba con el líder que nombras (None: nadie aún)
            self.reply(msg, {"type": "command_redirect", "leader": self.leader_id})
            return
        self.waiting[value] = msg  # learn() lo responde cuando se aplica
        slot = self.next_slot
        self.next_slot += 1
        self.spawn(self.phase2(slot, value))

    # ---- etapa 0 (dada): gana la primera propuesta que oye un nodo

    async def on_propose(self, msg: Message) -> None:
        slot = msg.body["slot"]
        if slot not in self.decided:
            self.learn(slot, msg.body["value"])  # gana el primer valor que un nodo oye para un hueco
        self.busy.discard(slot)

    # ---- el aceptador (etapa 1)

    async def on_prepare(self, msg: Message) -> None:
        b = msg.body
        if b["ballot"] > self.promised:
            self.promised = b["ballot"]
            self.see(b["ballot"])
            if self.role != "follower" and b["ballot"] > self.ballot:
                self.step_down()  # otro se presenta con una boleta más alta
            self.deadline = self.now() + self.timeout()  # da tiempo al candidato a ganar
            self.reply(msg, {"type": "promise", "ok": True, "accepted": self.accepted_from(b["slot"])})
        else:
            self.reply(msg, {"type": "promise", "ok": False, "promised": self.promised})

    async def on_accept(self, msg: Message) -> None:
        b = msg.body
        if b["ballot"] >= self.promised:
            self.promised = b["ballot"]
            self.accepted[b["slot"]] = (b["ballot"], b["value"])
            self.follow(b["ballot"])
            self.reply(msg, {"type": "accepted", "ok": True})
        else:
            self.reply(msg, {"type": "accepted", "ok": False, "promised": self.promised})

    # ---- el proponente (etapa 1): una ronda completa de Paxos por hueco

    async def submit(self, value: int) -> None:
        """Propone `value` hueco tras hueco hasta que se elija en uno."""
        start, tries = self.now(), 0
        async with self.proposing:  # una ronda a la vez por nodo
            while value in self.waiting and self.now() - start < GIVE_UP:
                slot = self.free_slot()
                self.busy.add(slot)
                try:
                    chosen = await self.paxos(slot, value)
                finally:
                    self.busy.discard(slot)
                if chosen == value:
                    return
                if chosen is None:  # superado: espera un rato aleatorio, o los proponentes se superan sin fin
                    tries += 1
                    await self.sleep(self.rng.uniform(0, BACKOFF * 2 ** min(tries, 4)))

    async def paxos(self, slot: int, value: int) -> int | None:
        """Paxos de un solo valor para un hueco. El valor elegido ahí, o None si ganó una boleta más alta."""
        ballot = self.next_ballot(max(self.promised, self.highest))
        self.see(ballot)
        replies = await self.broadcast({"type": "prepare", "ballot": ballot, "slot": slot})
        oks = self.count(replies)
        if len(oks) < self.majority:
            return None
        # Puede que algún aceptador ya aceptara un valor aquí: puede estar elegido, así que propón ese.
        prior = [r["accepted"][slot] for r in oks if slot in r["accepted"]]
        if prior:
            value = max(prior)[1]  # el de la boleta más alta
        replies = await self.broadcast({"type": "accept", "ballot": ballot, "slot": slot, "value": value})
        if len(self.count(replies)) < self.majority:
            return None
        self.decide(slot, value)
        return value

    # ---- Multi-Paxos (etapa 2): un líder, la fase 1 una vez para todos los huecos

    async def tick(self) -> None:
        if self.role == "leader":
            upto = self.first_undecided()
            for peer in self.peers:
                if self.now() - self.last_sent.get(peer, -1.0) >= HEARTBEAT:
                    self.last_sent[peer] = self.now()
                    self.send(peer, {"type": "heartbeat", "ballot": self.ballot, "upto": upto})
        elif self.role == "follower" and self.now() >= self.deadline:
            self.spawn(self.campaign())

    async def campaign(self) -> None:
        """La fase 1 una sola vez, para todos los huecos desde el primero sin decidir."""
        ballot = self.next_ballot(max(self.promised, self.highest))
        self.see(ballot)
        self.role, self.ballot, self.leader_id = "candidate", ballot, None
        self.deadline = self.now() + self.timeout()  # si falla, espera un tiempo aleatorio antes del siguiente intento
        start = self.first_undecided()
        replies = await self.broadcast({"type": "prepare", "ballot": ballot, "slot": start})
        oks = self.count(replies)
        if self.role != "candidate" or len(oks) < self.majority or self.highest > ballot:
            if self.role == "candidate":
                self.role = "follower"
            return
        self.role, self.leader_id = "leader", self.node_id
        self.last_sent.clear()
        # Cualquier valor que aceptó algún aceptador puede estar elegido: propónlo otra vez, con la boleta nueva.
        best: dict[int, tuple[int, int]] = {}
        for r in oks:
            for slot, (b, v) in r["accepted"].items():
                if slot >= start and (slot not in best or b > best[slot][0]):
                    best[slot] = (b, v)
        top = max(best, default=start - 1)
        self.next_slot = top + 1
        for slot in range(start, top + 1):
            if slot not in self.decided:  # un hueco en el que nadie aceptó nada: llénalo con un no-op
                self.spawn(self.phase2(slot, best[slot][1] if slot in best else NOOP))

    async def phase2(self, slot: int, value: int) -> None:
        """Aceptar y luego decidir, sin preparar: la boleta del líder vale para todos los huecos."""
        ballot = self.ballot
        body = {"type": "accept", "ballot": ballot, "slot": slot, "value": value}
        got: set[str] = set()

        async def one(node: str) -> None:
            while self.role == "leader" and self.ballot == ballot and slot not in self.decided:
                self.last_sent[node] = self.now()
                try:
                    reply = await self.rpc(node, body, RPC_TIMEOUT)
                except TimeoutError:
                    continue  # se perdió: envíalo otra vez
                if not reply.get("ok"):
                    self.preempted(reply.get("promised", 0))
                    return
                got.add(node)
                if len(got) >= self.majority and slot not in self.decided:
                    self.decide(slot, value)
                return

        for node in self.node_ids:
            self.spawn(one(node))

    async def on_heartbeat(self, msg: Message) -> None:
        b = msg.body
        if b["ballot"] < self.promised:  # un líder depuesto que aún no lo sabe
            self.send(msg.src, {"type": "preempt", "promised": self.promised})
            return
        self.follow(b["ballot"], msg.src)
        if b["upto"] > self.first_undecided():
            self.spawn(self.catch_up(msg.src))
