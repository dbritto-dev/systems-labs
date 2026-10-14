"""Laboratorio distributed_lock: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Cuatro workers comparten un informe en un servicio de almacenamiento, y solo un trabajo puede
escribirlo a la vez, así que un trabajo primero toma un cerrojo de un servicio de cerrojos. Los
clientes reparten trabajos (~0.8 por segundo) a cualquier worker; el worker toma el cerrojo,
escribe el informe en PARTS partes, lo suelta y responde. Cada mensaje tarda ~50 ms. Ahora mismo
el cerrojo nunca caduca, así que un dueño que se congela, se cae o queda aislado del servicio
de cerrojos bloquea todos los demás trabajos, quizá para siempre.

Haz las etapas en orden, en este archivo:

  Etapa 1  Plazos (leases): el servicio de cerrojos da el cerrojo por LEASE segundos y lo
           recupera cuando se acaba el plazo; el dueño lo renueva cada LEASE / 3 mientras corre
           su trabajo. Ahora nadie espera más de un par de segundos a un dueño muerto. Pero un
           dueño que estuvo congelado (una pausa de recolección de basura) despierta creyendo
           que aún tiene el cerrojo, y escribe encima del trabajo que tomó el cerrojo después.
  Etapa 2  Tokens de vallado (fencing tokens): cada concesión trae un número, uno más cada vez.
           El worker lo envía con cada escritura, y el almacenamiento rechaza una escritura cuyo
           token sea más viejo que el más nuevo que vio. Una escritura tardía de un cerrojo
           perdido rebota.

Cómo hablan tus nodos (mira core/net.py):
  self.node_id, self.node_ids        quién eres, y todos los nodos
  self.reply(msg, {...})             responde a una petición
  self.send(dest, {...})             envía sin esperar respuesta
  await self.rpc(dest, {...}, timeout=0.5)   envía y espera la respuesta (TimeoutError si se
                                     pierde, RPCError si es una respuesta de error)
  self.spawn(coroutine)              ejecuta algo en segundo plano (devuelve una tarea que puedes .cancel())
  await self.sleep(seconds)          espera; self.now() es el reloj (tiempo virtual)

El comprobador mira los mensajes: qué trabajo recibió un `acquire_ok`, y qué escrituras respondió
el almacenamiento con `write_ok`. Una escritura es *corrupta* cuando el almacenamiento la acepta
después de que un trabajo que tomó el cerrojo más tarde ya escribió. Mantén los nombres de los
mensajes de abajo.

Compruébalo:  LABS_LANG=es uv run pytest labs/distributed_lock
Mira una solución (¡después de intentarlo!):  labs/distributed_lock/es/reference.py
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError

LOCK, STORAGE = "lock", "storage"
LEASE = 2.0  # segundos que dura una concesión si no se renueva (etapa 1)
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
    """Da el cerrojo a un trabajo a la vez.

    Contrato:
      - `acquire` {job}  -> {"type": "acquire_ok"} (etapa 2: con "token") si el trabajo puede
                            tener el cerrojo, si no {"type": "error", "code": 11};
      - `renew` {job}    -> {"type": "renew_ok"} si el trabajo aún tiene el cerrojo, si no un
                            error (etapa 1);
      - `release` {job}  -> libera el cerrojo si lo tiene ese trabajo (sin respuesta).
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.holder = None  # el trabajo que tiene el cerrojo
        # Etapa 1: self.expires = 0.0, cuándo se acaba el plazo del dueño.
        # Etapa 2: self.token = 0, el token de la última concesión.

    async def on_acquire(self, msg: Message) -> None:
        # Etapa 1: el cerrojo también está libre cuando self.now() >= self.expires. Al darlo,
        # pon self.expires = self.now() + LEASE. (El mismo trabajo puede volver a tenerlo.)
        # Etapa 2: al darlo, self.token += 1 y pon "token": self.token en la respuesta.
        job = msg.body["job"]
        if self.holder is not None:
            self.reply(msg, {"type": "error", "code": 11, "text": "the lock is taken"})
            return
        self.holder = job
        self.reply(msg, {"type": "acquire_ok"})

    async def on_renew(self, msg: Message) -> None:
        """Etapa 1: si msg.body["job"] tiene el cerrojo y su plazo no se acabó, lleva
        self.expires a self.now() + LEASE y responde {"type": "renew_ok"}; si no, responde
        {"type": "error", "code": 22} (el plazo se fue: quizá otro tiene el cerrojo)."""
        raise NotImplementedError("TODO stage 1: LockService.on_renew")

    async def on_release(self, msg: Message) -> None:
        if self.holder == msg.body["job"]:
            self.holder = None


class Worker(Node):
    """Ejecuta los trabajos que le dan: toma el cerrojo, escribe PARTS partes, lo suelta, responde.

    Contrato:
      - `job` {job} -> {"type": "job_ok"} cuando todas las partes están escritas, si no un error;
      - escribe una parte con un rpc a STORAGE: {"type": "write", "job", "part", "data"}
        (etapa 2: y "token").
    """

    async def on_job(self, msg: Message) -> None:
        # Etapa 1: cuando tengas el cerrojo, consérvalo: renewing = self.spawn(self.renew(job)),
        # y renewing.cancel() en el finally.
        # Etapa 2: pon "token": token en cada escritura.
        job = msg.body["job"]
        token = await self.acquire(job)
        if token is None:
            self.reply(msg, {"type": "error", "code": 11, "text": "never got the lock"})
            return
        try:
            for part in range(PARTS):
                data = await compute(job, part)
                await self.rpc(STORAGE, {"type": "write", "job": job, "part": part, "data": data},
                               timeout=WRITE_TIMEOUT)
            self.reply(msg, {"type": "job_ok"})
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11, "text": "a write failed"})
        finally:
            self.send(LOCK, {"type": "release", "job": job})

    async def acquire(self, job: int):
        """Pide el cerrojo cada RETRY segundos; devuelve el token de la concesión (etapa 2; 0
        mientras no hay tokens), o None tras GIVE_UP segundos sin el cerrojo."""
        give_up = self.now() + GIVE_UP
        while self.now() < give_up:
            try:
                reply = await self.rpc(LOCK, {"type": "acquire", "job": job}, timeout=0.5)
                return reply.get("token", 0)
            except (TimeoutError, RPCError):
                await self.sleep(RETRY)
        return None

    async def renew(self, job: int) -> None:
        """Etapa 1: cada LEASE / 3 segundos, haz un rpc {"type": "renew", "job": job} a LOCK, para
        siempre. Deja que un RPCError o un TimeoutError termine el bucle: el plazo se fue."""
        raise NotImplementedError("TODO stage 1: Worker.renew")


class Storage(Node):
    """Guarda el informe compartido.

    Contrato:
      - `write` {job, part, data, token} -> {"type": "write_ok"}, o {"type": "error",
        "code": 22} cuando rechaza la escritura (etapa 2).
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.report: dict[int, str] = {}  # parte -> su texto
        # Etapa 2: self.highest = 0, el token más nuevo visto.

    def is_stale(self, token) -> bool:
        """Etapa 2: True cuando una escritura viene de un cerrojo perdido: sin token, o con un
        token más viejo (menor) que self.highest. Un token igual es la siguiente parte del
        mismo dueño."""
        raise NotImplementedError("TODO stage 2: Storage.is_stale")

    async def on_write(self, msg: Message) -> None:
        # Etapa 2: si self.is_stale(token), responde {"type": "error", "code": 22} y termina;
        # si no, recuerda self.highest = token, y escribe.
        self.report[msg.body["part"]] = msg.body["data"]
        self.reply(msg, {"type": "write_ok"})
