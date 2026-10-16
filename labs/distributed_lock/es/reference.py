"""Laboratorio distributed_lock: una solución que funciona (etapa 2). Léela después de intentar main.py.

Concesiones (leases): el servicio de cerrojos da el cerrojo por LEASE segundos y lo recupera cuando
se acaba ese tiempo, así que un dueño que se cayó o quedó aislado bloquea a todos LEASE como
mucho. El dueño lo renueva cada LEASE / 3 mientras corre su trabajo.

Tokens de vallado (fencing tokens): cada concesión trae un número, uno más que la anterior. El
worker lo envía con cada escritura, y el almacenamiento rechaza una escritura cuyo token sea más
viejo que uno que ya vio. Un dueño que estuvo en pausa, o cuya escritura se quedó en la red,
despierta con un token viejo, y su escritura tardía rebota en el almacenamiento en vez de pisar
datos más nuevos.
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError

LOCK, STORAGE = "lock", "storage"
LEASE = 2.0  # segundos que dura una concesión si no se renueva
RETRY = 0.1  # segundos entre intentos mientras el cerrojo está tomado
GIVE_UP = 8.0  # un trabajo deja de esperar el cerrojo pasado este tiempo
PARTS = 3  # un trabajo escribe el informe en estas partes
WORK = 0.1  # segundos de trabajo antes de cada parte
WRITE_TIMEOUT = 0.5  # segundos que se espera la respuesta del almacenamiento a una escritura


async def compute(job: int, part: int) -> str:
    """El trabajo antes de cada escritura: arma una parte del informe. (Dado: no lo cambies.)"""
    await asyncio.sleep(WORK)
    return f"report {job}, part {part + 1} of {PARTS}"


class LockService(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.holder = None  # el trabajo que tiene el cerrojo
        self.expires = 0.0  # cuándo vence su concesión
        self.token = 0  # el token de la última concesión

    def free(self) -> bool:
        return self.holder is None or self.now() >= self.expires

    async def on_acquire(self, msg: Message) -> None:
        job = msg.body["job"]
        if not self.free() and self.holder != job:
            self.reply(msg, {"type": "error", "code": 11, "text": "the lock is taken"})
            return
        self.holder, self.expires = job, self.now() + LEASE
        self.token += 1
        self.reply(msg, {"type": "acquire_ok", "token": self.token, "lease": LEASE})

    async def on_renew(self, msg: Message) -> None:
        if self.holder != msg.body["job"] or self.free():
            self.reply(msg, {"type": "error", "code": 22, "text": "the lease is gone"})
            return
        self.expires = self.now() + LEASE
        self.reply(msg, {"type": "renew_ok", "lease": LEASE})

    async def on_release(self, msg: Message) -> None:
        if self.holder == msg.body["job"]:
            self.holder = None


class Worker(Node):
    async def on_job(self, msg: Message) -> None:
        job = msg.body["job"]
        token = await self.acquire(job)
        if token is None:
            self.reply(msg, {"type": "error", "code": 11, "text": "never got the lock"})
            return
        renewing = self.spawn(self.renew(job))
        try:
            for part in range(PARTS):
                data = await compute(job, part)
                await self.rpc(STORAGE, {"type": "write", "job": job, "part": part, "data": data,
                                         "token": token}, timeout=WRITE_TIMEOUT)
            self.reply(msg, {"type": "job_ok"})
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11, "text": "a write failed"})
        finally:
            renewing.cancel()
            self.send(LOCK, {"type": "release", "job": job})

    async def acquire(self, job: int):
        """El token de vallado de una concesión nueva, o None tras GIVE_UP segundos sin ella."""
        give_up = self.now() + GIVE_UP
        while self.now() < give_up:
            try:
                reply = await self.rpc(LOCK, {"type": "acquire", "job": job}, timeout=0.5)
                return reply["token"]
            except (TimeoutError, RPCError):
                await self.sleep(RETRY)
        return None

    async def renew(self, job: int) -> None:
        """Mantén la concesión mientras corre el trabajo (una renovación rechazada termina el bucle)."""
        while True:
            await self.sleep(LEASE / 3)
            await self.rpc(LOCK, {"type": "renew", "job": job}, timeout=0.5)


class Storage(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.report: dict[int, str] = {}  # parte -> su texto
        self.highest = 0  # el token de vallado más nuevo visto

    def is_stale(self, token) -> bool:
        """Una escritura sin token, o con uno más viejo que el más nuevo visto, viene de un cerrojo perdido."""
        return token is None or token < self.highest

    async def on_write(self, msg: Message) -> None:
        token = msg.body.get("token")
        if self.is_stale(token):
            self.reply(msg, {"type": "error", "code": 22, "text": f"token {token} is older than {self.highest}"})
            return
        self.highest = token
        self.report[msg.body["part"]] = msg.body["data"]
        self.reply(msg, {"type": "write_ok"})
