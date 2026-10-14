"""Laboratorio raft: una solución que funciona (todas las etapas). Léela después de intentar es/main.py."""

from __future__ import annotations

import random
from dataclasses import dataclass

from core.net import Message, Node

ELECTION_TIMEOUT = (0.3, 0.6)  # segundos sin líder antes de presentarse a una elección
HEARTBEAT = 0.1  # el líder envía AppendEntries al menos así de seguido
TICK = 0.05  # cada cuánto se ejecuta tick()
RPC_TIMEOUT = 0.25
BATCH = 50  # entradas por AppendEntries como mucho


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
        self.role = "follower"
        self.leader_id: str | None = None
        self.commit_index = 0  # cuántas entradas del log están consolidadas
        self.rng = random.Random(node_id)  # sus propios timeouts: los nodos no los agotan a la vez
        self.peers = [n for n in node_ids if n != node_id]
        self.majority = len(node_ids) // 2 + 1
        self.deadline = self.now() + self.timeout()
        # Estado del líder.
        self.next_index: dict[str, int] = {}
        self.match_index: dict[str, int] = {}
        self.in_flight: set[str] = set()
        self.last_sent: dict[str, float] = {}
        self.waiting: dict[int, Message] = {}  # posición en el log (desde 1) -> petición de cliente por responder
        self.votes: set[str] = set()
        self.every(TICK, self.tick)

    def timeout(self) -> float:
        return self.rng.uniform(*ELECTION_TIMEOUT)

    # ---- el reloj

    async def tick(self) -> None:
        if self.role == "leader":
            for peer in self.peers:
                self.replicate(peer)
        elif self.now() >= self.deadline:
            self.start_election()

    # ---- elecciones

    def become_follower(self, term: int, leader: str | None = None) -> None:
        if term > self.current_term:
            self.current_term, self.voted_for = term, None
        self.role = "follower"
        self.leader_id = leader
        self.waiting.clear()  # un líder depuesto ya no responde (los clientes reintentarán)

    def start_election(self) -> None:
        self.current_term += 1
        self.role, self.voted_for, self.votes = "candidate", self.node_id, {self.node_id}
        self.leader_id = None
        self.deadline = self.now() + self.timeout()
        last_term = self.log[-1].term if self.log else 0
        body = {"type": "request_vote", "term": self.current_term, "candidate": self.node_id,
                "last_index": len(self.log), "last_term": last_term}
        for peer in self.peers:
            self.spawn(self.ask_vote(peer, body, self.current_term))

    async def ask_vote(self, peer: str, body: dict, term: int) -> None:
        reply = await self.rpc(peer, body, timeout=RPC_TIMEOUT)
        if reply["term"] > self.current_term:
            self.become_follower(reply["term"])
            return
        if self.role == "candidate" and self.current_term == term and reply["granted"]:
            self.votes.add(peer)
            if len(self.votes) >= self.majority:
                self.become_leader()

    def become_leader(self) -> None:
        self.role, self.leader_id = "leader", self.node_id
        self.next_index = {p: len(self.log) for p in self.peers}
        self.match_index = {p: 0 for p in self.peers}
        self.in_flight.clear()
        self.last_sent.clear()
        for peer in self.peers:
            self.replicate(peer)

    async def on_request_vote(self, msg: Message) -> None:
        b = msg.body
        if b["term"] > self.current_term:
            self.become_follower(b["term"])
        last_term = self.log[-1].term if self.log else 0
        # La restricción de elección: vota solo a un candidato cuyo log esté al menos igual de al día.
        up_to_date = (b["last_term"], b["last_index"]) >= (last_term, len(self.log))
        granted = (b["term"] == self.current_term and self.voted_for in (None, b["candidate"])
                   and up_to_date)
        if granted:
            self.voted_for = b["candidate"]
            self.deadline = self.now() + self.timeout()
        self.reply(msg, {"type": "request_vote_ok", "term": self.current_term, "granted": granted})

    # ---- replicación

    def replicate(self, peer: str) -> None:
        """Envía a `peer` lo que le falta (o un latido), una petición a la vez."""
        if peer in self.in_flight:
            return
        start = self.next_index[peer]
        entries = self.log[start:start + BATCH]
        if not entries and self.now() - self.last_sent.get(peer, -1.0) < HEARTBEAT:
            return
        prev_term = self.log[start - 1].term if start > 0 else 0
        body = {"type": "append_entries", "term": self.current_term, "leader": self.node_id,
                "prev_index": start, "prev_term": prev_term,
                "entries": [(e.term, e.command) for e in entries], "commit": self.commit_index}
        self.in_flight.add(peer)
        self.last_sent[peer] = self.now()
        self.spawn(self.append(peer, body, self.current_term))

    async def append(self, peer: str, body: dict, term: int) -> None:
        try:
            reply = await self.rpc(peer, body, timeout=RPC_TIMEOUT)
        finally:
            self.in_flight.discard(peer)
        if reply["term"] > self.current_term:
            self.become_follower(reply["term"])
            return
        if self.role != "leader" or self.current_term != term:
            return
        if reply["success"]:
            self.match_index[peer] = max(self.match_index[peer], reply["match"])
            self.next_index[peer] = self.match_index[peer]
            self.advance_commit()
        else:
            self.next_index[peer] = max(0, min(self.next_index[peer] - 1, reply["match"]))

    def advance_commit(self) -> None:
        for n in range(len(self.log), self.commit_index, -1):
            # Solo las entradas del término actual se consolidan contando (Raft, figura 8).
            if self.log[n - 1].term != self.current_term:
                break
            if 1 + sum(1 for p in self.peers if self.match_index[p] >= n) >= self.majority:
                self.commit_index = n
                break
        for index in [i for i in self.waiting if i <= self.commit_index]:
            self.reply(self.waiting.pop(index), {"type": "command_ok", "index": index})

    async def on_append_entries(self, msg: Message) -> None:
        b = msg.body
        if b["term"] < self.current_term:  # un líder viejo: recházalo y dile el término
            self.reply(msg, {"type": "append_entries_ok", "term": self.current_term,
                             "success": False, "match": len(self.log)})
            return
        self.become_follower(b["term"], b["leader"])
        self.deadline = self.now() + self.timeout()
        prev = b["prev_index"]
        if prev > len(self.log) or (prev > 0 and self.log[prev - 1].term != b["prev_term"]):
            self.reply(msg, {"type": "append_entries_ok", "term": self.current_term,
                             "success": False, "match": min(len(self.log), prev - 1)})
            return
        for i, (term, command) in enumerate(b["entries"]):
            pos = prev + i
            if pos < len(self.log) and self.log[pos].term != term:
                del self.log[pos:]  # un conflicto: bórrala y todo lo que sigue
            if pos >= len(self.log):
                self.log.append(Entry(term, command))
        match = prev + len(b["entries"])
        self.commit_index = max(self.commit_index, min(b["commit"], match))
        self.reply(msg, {"type": "append_entries_ok", "term": self.current_term, "success": True,
                         "match": match})

    # ---- clientes

    async def on_command(self, msg: Message) -> None:
        if self.role != "leader":
            self.reply(msg, {"type": "command_redirect", "leader": self.leader_id})
            return
        self.log.append(Entry(self.current_term, msg.body["value"]))
        self.waiting[len(self.log)] = msg  # se responde cuando esté consolidada
        for peer in self.peers:
            self.replicate(peer)
