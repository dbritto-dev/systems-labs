"""Laboratorio quorum: una solución que funciona (etapa 2). Léela después de intentar main.py.

Quórums: una escritura va a las N=3 réplicas de la clave y se confirma tras W=2 de ellas; una
lectura pregunta a las réplicas y responde con la más nueva de R=2 respuestas. W + R > N, así
que una lectura siempre se solapa con la última escritura confirmada, y un nodo enfermo no
cambia nada para los clientes.

Reparación: cada escritura que se perdió una réplica se convierte en una pista (hint), que se
reenvía (en un lote por réplica) cada medio segundo hasta que esa réplica la confirme
(hinted handoff); y una lectura que ve una réplica atrasada le envía la versión más nueva
(read repair).
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError

N, W, R = 3, 2, 2
TIMEOUT = 0.5  # cuánto esperar a una réplica
HAND_OFF = 0.5  # cada cuánto reenviar las pistas
LOWEST = (-1.0, "")  # la versión de una clave que una réplica no tiene


def replicas_for(key: str, node_ids: list[str], n: int = N) -> list[str]:
    """Los n nodos que guardan `key`: su nodo de casa y los siguientes del anillo. (Dado: no lo cambies.)"""
    home = int(key[1:]) % len(node_ids)
    return [node_ids[(home + j) % len(node_ids)] for j in range(n)]


class QuorumNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple] = {}
        self.hints: dict[str, dict[str, tuple]] = {}  # réplica -> {clave: (versión, valor)}
        self.every(HAND_OFF, self.hand_off)

    # ---- como réplica

    def keep(self, key: str, version, value) -> None:
        """Quédate con lo más nuevo entre lo que tienes y lo que te llega."""
        version = tuple(version)
        old = self.store.get(key)
        if old is None or version > tuple(old[0]):
            self.store[key] = (version, value)

    async def on_store(self, msg: Message) -> None:
        self.keep(msg.body["key"], msg.body["version"], msg.body["value"])
        self.reply(msg, {"type": "store_ok"})

    async def on_store_many(self, msg: Message) -> None:
        for key, version, value in msg.body["items"]:
            self.keep(key, version, value)
        self.reply(msg, {"type": "store_many_ok"})

    async def on_fetch(self, msg: Message) -> None:
        entry = self.store.get(msg.body["key"])
        version, value = entry if entry else (LOWEST, None)
        self.reply(msg, {"type": "fetch_ok", "version": version, "value": value})

    # ---- como coordinador

    async def replicate(self, replica: str, key: str, version, value) -> bool:
        body = {"type": "store", "key": key, "version": version, "value": value}
        try:
            await self.rpc(replica, body, timeout=TIMEOUT)
            return True
        except (TimeoutError, RPCError):
            hints = self.hints.setdefault(replica, {})
            if key not in hints or tuple(version) > tuple(hints[key][0]):
                hints[key] = (version, value)  # entrégasela más tarde
            return False

    async def on_put(self, msg: Message) -> None:
        key, value = msg.body["key"], msg.body["value"]
        version = (self.now(), self.node_id)
        tasks = [asyncio.ensure_future(self.replicate(r, key, version, value))
                 for r in replicas_for(key, self.node_ids)]
        acks = 0
        for done in asyncio.as_completed(tasks):
            acks += await done
            if acks >= W:
                self.reply(msg, {"type": "put_ok"})
                return
        self.reply(msg, {"type": "error", "code": 11, "text": "not enough replicas"})

    async def fetch(self, replica: str, key: str):
        try:
            reply = await self.rpc(replica, {"type": "fetch", "key": key}, timeout=TIMEOUT)
            return replica, tuple(reply["version"]), reply["value"]
        except (TimeoutError, RPCError):
            return None

    async def on_get(self, msg: Message) -> None:
        key = msg.body["key"]
        tasks = [asyncio.ensure_future(self.fetch(r, key)) for r in replicas_for(key, self.node_ids)]
        replies = []
        for done in asyncio.as_completed(tasks):
            reply = await done
            if reply is not None:
                replies.append(reply)
            if len(replies) >= R:
                break
        if len(replies) < R:
            self.reply(msg, {"type": "error", "code": 11, "text": "not enough replicas"})
            return
        _, version, value = max(replies, key=lambda r: r[1])
        self.reply(msg, {"type": "get_ok", "value": value})
        self.spawn(self.read_repair(key, tasks, version, value))

    async def read_repair(self, key: str, tasks, version, value) -> None:
        """Cuando todas las réplicas respondieron (o se agotó su tiempo), envía la versión más nueva a las atrasadas."""
        for reply in await asyncio.gather(*tasks):
            if reply is not None and reply[1] < version:
                self.send(reply[0], {"type": "store", "key": key, "version": version, "value": value})

    async def hand_off(self) -> None:
        for replica, items in list(self.hints.items()):
            if items:
                self.spawn(self.hand_over(replica, dict(items)))

    async def hand_over(self, replica: str, items: dict) -> None:
        body = {"type": "store_many", "items": [(k, v, x) for k, (v, x) in items.items()]}
        try:
            await self.rpc(replica, body, timeout=TIMEOUT)
        except (TimeoutError, RPCError):
            return
        hints = self.hints.get(replica, {})
        for k, entry in items.items():
            if hints.get(k) == entry:  # no la reemplazó una pista más nueva mientras tanto
                del hints[k]
