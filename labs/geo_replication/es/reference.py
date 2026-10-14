"""Laboratorio geo_replication: una solución que funciona (etapa 2). Léela después de intentar main.py.

Escrituras en cada región: la escritura de un usuario la acepta la región a la que llega (la suya,
o la siguiente cuando la suya está caída) y se confirma cuando una segunda región también la tiene,
la más cercana que responda. Las lecturas se responden con la copia de la región, salvo que el token
de sesión del usuario diga que ya escribió o vio algo más nuevo: entonces la región lo busca antes en
las otras. Una región que se perdió escrituras (estuvo caída, aislada, o tras un enlace lento) las
recibe después, como pistas (hinted handoff). Conflictos: gana la versión más nueva de una clave
(gana el último que escribe); una clave solo la escribe su dueño, una petición a la vez, así que una
versión más nueva siempre es la escritura posterior.
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError
from labs.geo_replication.api import REGIONS, nearest

PRIMARY = "us"  # etapas 0 y 1: la región que recibe todas las escrituras (la etapa 2 no tiene)
TIMEOUT = 0.4  # espera esto a otra región
SHIP_EVERY = 0.1  # etapa 1: envía las escrituras nuevas del primario a las réplicas con esta frecuencia
HAND_OFF = 1.0  # etapa 2: reenvía con esta frecuencia las escrituras que se perdió una región
HAND_OFF_TIMEOUT = 1.0  # etapa 2: un lote de pistas puede cruzar un enlace lento


class RegionNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple[float, int]] = {}  # clave -> (versión, valor)
        self.log: list[tuple[str, float, int]] = []  # etapa 1: escrito aquí, aún sin enviar
        self.hints: dict[str, dict[str, tuple[float, int]]] = {r: {} for r in REGIONS if r != node_id}
        self.every(HAND_OFF, self.hand_off)

    # ---- dado

    def keep(self, key: str, version: float, value: int) -> bool:
        """Guarda la más nueva entre lo que tenemos y lo que llegó (gana el último que escribe). True si cambió."""
        old = self.store.get(key)
        if old is None or version > old[0]:
            self.store[key] = (version, value)
            return True
        return False

    async def forward(self, msg: Message, region: str) -> None:
        """Reenvía la petición de un usuario a otra región y devuelve su respuesta (error 11 si no hay)."""
        try:
            reply = await self.rpc(region, {k: v for k, v in msg.body.items() if k != "msg_id"}, timeout=TIMEOUT)
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11, "text": f"{region} did not answer"})
            return
        self.reply(msg, {k: v for k, v in reply.items() if k != "in_reply_to"})

    # ---- usuarios

    async def on_read(self, msg: Message) -> None:
        key, token = msg.body["key"], msg.body.get("token", 0)
        version, value = self.store.get(key, (0, None))
        if version < token:  # esta sesión escribió o vio algo más nuevo: búscalo primero
            found = await self.fetch(key, token)
            if found is None:
                self.reply(msg, {"type": "error", "code": 11, "text": "no region has this session's version"})
                return
            version, value = found
        self.reply(msg, {"type": "read_ok", "value": value, "version": version})

    async def on_write(self, msg: Message) -> None:
        key, value = msg.body["key"], msg.body["value"]
        version = max(self.now(), msg.body.get("token", 0) + 1e-6)
        self.keep(key, version, value)
        if await self.replicate(key, version, value):
            self.reply(msg, {"type": "write_ok", "version": version})
        else:  # solo esta región la tiene: no es seguro confirmarla
            self.reply(msg, {"type": "error", "code": 11, "text": "no other region took the write"})

    # ---- etapa 1: el lado de las réplicas (la etapa 2 lo conserva)

    async def ship(self) -> None:
        pass  # la etapa 2 replica cada escritura en el momento

    async def on_replicate(self, msg: Message) -> None:
        for key, version, value in msg.body["items"]:
            self.keep(key, version, value)
        self.reply(msg, {"type": "replicate_ok"})

    # ---- etapa 2: cada región acepta escrituras

    async def replicate(self, key: str, version: float, value: int) -> bool:
        """Envía la escritura a cada otra región; True en cuanto una de ellas la tenga."""
        tasks = [asyncio.ensure_future(self.send_to(r, key, version, value)) for r in nearest(self.node_id)]
        for done in asyncio.as_completed(tasks):
            if await done:
                return True
        return False

    async def send_to(self, region: str, key: str, version: float, value: int) -> bool:
        """Una escritura a una región; una pista si no respondió."""
        body = {"type": "replicate", "items": [(key, version, value)]}
        try:
            await self.rpc(region, body, timeout=TIMEOUT)
            return True
        except (TimeoutError, RPCError):
            hints = self.hints[region]
            if key not in hints or version > hints[key][0]:
                hints[key] = (version, value)  # entrégala más tarde
            return False

    async def hand_off(self) -> None:
        for region, hints in self.hints.items():
            if hints:
                self.spawn(self.hand_over(region, dict(hints)))

    async def hand_over(self, region: str, items: dict[str, tuple[float, int]]) -> None:
        body = {"type": "replicate", "items": [(k, v, x) for k, (v, x) in items.items()]}
        try:
            await self.rpc(region, body, timeout=HAND_OFF_TIMEOUT)
        except (TimeoutError, RPCError):
            return
        hints = self.hints[region]
        for k, entry in items.items():
            if hints.get(k) == entry:  # no la reemplazó una más nueva mientras tanto
                del hints[k]

    async def on_fetch(self, msg: Message) -> None:
        version, value = self.store.get(msg.body["key"], (0, None))
        self.reply(msg, {"type": "fetch_ok", "version": version, "value": value})

    async def fetch(self, key: str, token: float) -> tuple[float, int] | None:
        """Pide `key` a las otras regiones; la primera respuesta al menos tan nueva como `token` (guardada aquí también)."""

        async def ask(region: str):
            try:
                return await self.rpc(region, {"type": "fetch", "key": key}, timeout=TIMEOUT)
            except (TimeoutError, RPCError):
                return None

        for done in asyncio.as_completed([asyncio.ensure_future(ask(r)) for r in nearest(self.node_id)]):
            reply = await done
            if reply is not None and reply["value"] is not None and reply["version"] >= token:
                self.keep(key, reply["version"], reply["value"])
                return reply["version"], reply["value"]
        return None
