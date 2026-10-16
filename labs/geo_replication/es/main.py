"""Laboratorio geo_replication: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un servicio de perfiles y ajustes corre en tres regiones: us, eu y ap, un `RegionNode` en cada una
(su id de nodo es su región). Hay usuarios en las tres, y el balanceador global manda a cada uno a
su propia región. Dentro de una región un mensaje tarda ~1 ms; entre regiones cruza un océano:
us-eu ~70 ms de ida, us-ap ~100 ms, eu-ap ~150 ms. Ahora mismo cada región reenvía cada lectura y
cada escritura a una región primaria, us: los usuarios de Europa y Asia esperan un viaje de ida y
vuelta por el océano para todo, y cuando us cae, nadie puede hacer nada.

Haz las etapas en orden, en este archivo:

  Etapa 1  Réplicas de lectura. Cada región guarda una copia y responde las lecturas con ella.
           Las escrituras siguen yendo al primario, que las confirma y las envía a las otras
           regiones de forma asíncrona, en lotes cada SHIP_EVERY segundos. Leer se vuelve rápido;
           pero un usuario en eu que guarda y recarga puede no ver su propio cambio, las últimas
           escrituras del primario existen en una sola región, y con us caída nadie puede escribir.
  Etapa 2  Escrituras en cada región. Cualquier región acepta una escritura (la del usuario, o la
           siguiente cuando la suya está caída), y la confirma solo cuando una segunda región
           también la tiene (la primera de las otras dos en responder): un océano por escritura,
           nunca dos, y ninguna escritura confirmada vive en una sola región. Envía más tarde las
           escrituras que se perdió una región (pistas). Token de sesión: cada petición lleva la
           versión más nueva de esa clave que el usuario escribió o vio; una región cuya copia es
           más vieja la busca en las otras antes de responder, así nadie deja de ver sus propias
           escrituras, lo atienda la región que lo atienda.

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      tu región ("us", "eu" o "ap"), y las tres
  self.reply(msg, {...})           responde a una petición
  self.send(dest, {...})           envía sin esperar respuesta
  await self.rpc(dest, {...}, timeout=TIMEOUT)   envía y espera la respuesta (TimeoutError si se pierde)
  self.every(seconds, coroutine_function)        ejecuta algo cada cierto tiempo
  self.spawn(coroutine)            ejecuta algo en segundo plano
  self.now()                       el reloj (aquí es el mismo en todas las regiones: sirve de versión)
  nearest(region)                  las otras regiones, la más cercana primero (labs/geo_replication/api.py)

Guarda tus datos en `self.store`, como {key: (version, value)}: el comprobador mira ahí.

Compruébalo:  uv run pytest labs/geo_replication
Mira una solución (¡después de intentarlo!):  labs/geo_replication/es/reference.py
"""

from __future__ import annotations

import asyncio  # etapa 2: asyncio.ensure_future, asyncio.as_completed

from core.net import Message, Node, RPCError
from labs.geo_replication.api import REGIONS, nearest  # etapa 2: nearest(self.node_id)

PRIMARY = "us"  # etapas 0 y 1: la región que recibe todas las escrituras (la etapa 2 no tiene)
TIMEOUT = 0.4  # espera esto a otra región
SHIP_EVERY = 0.1  # etapa 1: envía las escrituras nuevas del primario a las réplicas con esta frecuencia
HAND_OFF = 1.0  # etapa 2: reenvía con esta frecuencia las escrituras que se perdió una región
HAND_OFF_TIMEOUT = 1.0  # etapa 2: un lote de pistas puede cruzar un enlace lento


class RegionNode(Node):
    """El servicio de una región. Las peticiones de los usuarios (su aplicación añade el token de sesión):

      read  {key, token}          -> {"type": "read_ok", "value": valor o None, "version": versión o 0}
      write {key, value, token}   -> {"type": "write_ok", "version": versión}

    `token` es la versión más nueva de esa clave que este usuario escribió o leyó (0 si ninguna).
    Responde {"type": "error", "code": 11} cuando no puedas atender una petición: la aplicación
    reintenta una vez, en la siguiente región. Una clave solo la escribe su dueño, una petición a la
    vez. `self.store[key] = (version, value)`: lo que guarda esta región. Siempre gana la versión
    más nueva (`keep`).
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.store: dict[str, tuple[float, int]] = {}  # clave -> (versión, valor)
        self.log: list[tuple[str, float, int]] = []  # etapa 1: escrito aquí, aún sin enviar
        self.hints: dict[str, dict[str, tuple[float, int]]] = {r: {} for r in REGIONS if r != node_id}
        # Etapa 1: self.every(SHIP_EVERY, self.ship)
        # Etapa 2: en su lugar, self.every(HAND_OFF, self.hand_off)

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
        # Etapa 1: responde desde self.store, en cada región: version, value = self.store.get(key, (0, None)).
        # Etapa 2: si esa versión es más vieja que msg.body["token"], primero `await self.fetch(key, token)`;
        #          si ninguna región la tiene, responde error 11.
        if self.node_id != PRIMARY:
            await self.forward(msg, PRIMARY)
            return
        version, value = self.store.get(msg.body["key"], (0, None))
        self.reply(msg, {"type": "read_ok", "value": value, "version": version})

    async def on_write(self, msg: Message) -> None:
        # Etapa 1: en el primario, añade también (key, version, value) a self.log para ship().
        # Etapa 2: en cada región: guárdala, luego `await self.replicate(key, version, value)`; responde
        #          write_ok si devolvió True, si no error 11. Haz la versión más nueva que el token:
        #          max(self.now(), token + 1e-6).
        if self.node_id != PRIMARY:
            await self.forward(msg, PRIMARY)
            return
        key, value = msg.body["key"], msg.body["value"]
        version = self.now()
        self.keep(key, version, value)
        self.reply(msg, {"type": "write_ok", "version": version})

    # ---- etapa 1: réplicas en cada región

    async def ship(self) -> None:
        """Etapa 1. En el primario, cada SHIP_EVERY segundos: envía lo que tiene self.log a cada otra
        región en un solo mensaje, {"type": "replicate", "items": [(key, version, value), ...]} con
        self.send (sin esperar: replicación asíncrona), y vacía el log."""
        raise NotImplementedError("PENDIENTE etapa 1: ship()")

    async def on_replicate(self, msg: Message) -> None:
        """Etapa 1. Guarda cada (key, version, value) de msg.body["items"] y responde
        {"type": "replicate_ok"} (la etapa 2 espera esa respuesta; en la etapa 1 nadie la espera)."""
        raise NotImplementedError("PENDIENTE etapa 1: on_replicate()")

    # ---- etapa 2: cada región acepta escrituras

    async def replicate(self, key: str, version: float, value: int) -> bool:
        """Etapa 2. Envía la escritura a cada otra región a la vez (`self.send_to`, una tarea cada una:
        asyncio.ensure_future) y devuelve True en cuanto una de ellas responda True (usa
        asyncio.as_completed); False si ninguna lo hace. No esperes a la segunda."""
        raise NotImplementedError("PENDIENTE etapa 2: replicate()")

    async def send_to(self, region: str, key: str, version: float, value: int) -> bool:
        """Etapa 2. Una escritura a una región: un rpc {"type": "replicate", "items": [(key, version,
        value)]} con timeout=TIMEOUT. True si respondió. Si no (TimeoutError o RPCError), guarda una
        pista, self.hints[region][key] = (version, value) (salvo que ya tenga una más nueva), y
        devuelve False."""
        raise NotImplementedError("PENDIENTE etapa 2: send_to()")

    async def hand_off(self) -> None:
        """Etapa 2. Cada HAND_OFF segundos: por cada región con pistas, `self.spawn(self.hand_over(
        region, dict(hints)))` (una copia: pueden llegar pistas nuevas mientras tanto)."""
        raise NotImplementedError("PENDIENTE etapa 2: hand_off()")

    async def hand_over(self, region: str, items: dict[str, tuple[float, int]]) -> None:
        """Etapa 2. Envía las pistas en un rpc {"type": "replicate", "items": [...]} con
        timeout=HAND_OFF_TIMEOUT. Si respondió, olvida cada pista que siga siendo la que enviaste."""
        raise NotImplementedError("PENDIENTE etapa 2: hand_over()")

    async def on_fetch(self, msg: Message) -> None:
        """Etapa 2. Responde {"type": "fetch_ok", "version": version, "value": value} desde self.store
        ((0, None) si no tienes la clave)."""
        raise NotImplementedError("PENDIENTE etapa 2: on_fetch()")

    async def fetch(self, key: str, token: float) -> tuple[float, int] | None:
        """Etapa 2. Pide key a las otras regiones a la vez (un rpc {"type": "fetch", "key": key} a cada
        una, timeout=TIMEOUT). Devuelve (version, value) de la primera respuesta con valor cuya
        versión sea al menos token, después de guardarla aquí también; None si ninguna la tiene."""
        raise NotImplementedError("PENDIENTE etapa 2: fetch()")
