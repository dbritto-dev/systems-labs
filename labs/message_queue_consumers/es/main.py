"""Laboratorio message_queue_consumers: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los productores envían ~40 trabajos por segundo a una cola como Amazon SQS. Siete procesos workers
los reciben, seis a la vez cada uno, y llaman a `Consumer.process(msg)` por cada mensaje. Un
mensaje recibido queda invisible para los demás workers durante VISIBILITY segundos (el timeout
de visibilidad); si no se borra antes, la cola se lo da a otro worker.

Ahora mismo `process` borra (confirma) el mensaje en cuanto llega, y después hace el trabajo.
Cuando un proceso worker cae a mitad de trabajo (un despliegue, un OOM), o el trabajo falla, el
trabajo se pierde.

Haz las etapas en orden, en este archivo:

  Etapa 1  Confirma al terminar: borra el mensaje solo cuando `handle(msg)` haya salido bien, así
           una caída o un fallo lo deja en la cola para otro worker. Mientras trabajas, mantenlo
           oculto: `heartbeat(msg)` alarga su visibilidad cada HEARTBEAT segundos (un latido), así
           un trabajo lento no se le da a un segundo worker mientras el primero sigue con él.
  Etapa 2  Reintentos limitados y una cola de mensajes muertos (DLQ): cuando un trabajo falla,
           `on_failure(msg)` oculta el mensaje `backoff(receive_count)` segundos (más cada vez,
           con jitter); cuando ya se ha entregado MAX_RECEIVES veces es veneno: apártalo en la DLQ
           y bórralo, para que deje de volver.

Lo que tienes (mira labs/message_queue_consumers/api.py):
  msg.id, msg.receive_count                    receive_count es 1 en la primera entrega
  await self.queue.delete(msg) -> bool         confirmar: borra el mensaje para siempre
  await self.queue.change_visibility(msg, s)   ocúltalo s segundos más -> bool (False: ya no está
                                               o ahora lo tiene otro worker)
  await self.dlq.send(msg)                     apártalo en la cola de mensajes muertos
  await self.handle(msg)                       haz el trabajo; lanza JobFailed cuando falla

Compruébalo:  LABS_LANG=es uv run pytest labs/message_queue_consumers
Mira una solución (¡después de intentarlo!):  labs/message_queue_consumers/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from labs.message_queue_consumers.api import VISIBILITY, JobFailed, Message

HEARTBEAT = 0.5  # segundos entre latidos: bien dentro del timeout de visibilidad
MAX_RECEIVES = 4  # entregas antes de apartar un mensaje en la DLQ
BACKOFF_BASE = 1.0  # segundos antes de la 2.ª entrega; se duplica cada vez
BACKOFF_CAP = 8.0


class Consumer:
    """Trabaja en los mensajes de un proceso worker.

    Contrato:
      - `await consumer.process(msg)` se llama una vez por entrega. Devuelve cuando hayas acabado
        con esta entrega (el trabajo salió bien y lo confirmaste, o falló y te ocupaste de él).
      - Un trabajo nunca debe perderse: confirma (borra) solo después de que `handle(msg)` salga bien.
      - Un trabajo no debería hacerlo dos workers a la vez: mantén el mensaje oculto mientras
        corre `handle`.
      - Un mensaje que sigue fallando debe acabar en la DLQ, no en la cola para siempre.
    """

    def __init__(self, queue, dlq, handle, rng: random.Random | None = None) -> None:
        self.queue = queue
        self.dlq = dlq
        self.handle = handle
        self.rng = rng or random.Random(0)  # para backoff(): las ejecuciones se repiten

    async def process(self, msg: Message) -> None:
        # Etapa 1: arranca el latido como tarea, `beat = asyncio.ensure_future(self.heartbeat(msg))`,
        #          luego `await self.handle(msg)`, y solo entonces `await self.queue.delete(msg)`.
        #          Cancela el latido al acabar, también si el trabajo falla o el proceso cae
        #          (`try: ... finally: beat.cancel()`). Un trabajo que falla: solo devuelve; el
        #          mensaje vuelve cuando se acabe su timeout de visibilidad.
        # Etapa 2: cuando handle lanza JobFailed, cancela el latido y `await self.on_failure(msg)`.
        await self.queue.delete(msg)  # confirmar al recibir: si caemos o fallamos ahora, el trabajo se pierde
        try:
            await self.handle(msg)
        except JobFailed:
            pass

    async def heartbeat(self, msg: Message) -> None:
        """Etapa 1. Cada HEARTBEAT segundos, `await self.queue.change_visibility(msg, VISIBILITY)`
        para que el mensaje siga oculto mientras trabajas. Para cuando devuelva False (el mensaje
        ya no está, o ahora lo tiene otro worker). Corre hasta que lo cancelen."""
        raise NotImplementedError("PENDIENTE etapa 1: heartbeat(msg)")

    async def on_failure(self, msg: Message) -> None:
        """Etapa 2. El trabajo falló. Si `msg.receive_count >= MAX_RECEIVES`, es veneno:
        `await self.dlq.send(msg)`, y luego bórralo de la cola. Si no, ocúltalo
        `backoff(msg.receive_count, self.rng)` segundos, para reintentarlo más tarde."""
        raise NotImplementedError("PENDIENTE etapa 2: on_failure(msg)")


def backoff(receive_count: int, rng: random.Random | None = None) -> float:
    """Etapa 2. Segundos de espera antes de la próxima entrega: BACKOFF_BASE duplicado por cada
    entrega hasta ahora (1, 2, 4 ... para receive_count 1, 2, 3 ...), como mucho BACKOFF_CAP, con
    "equal jitter": la mitad fija y la otra mitad una cantidad al azar (`(rng or random).uniform`).

    >>> 0.5 <= backoff(1, random.Random(1)) <= 1.0
    True
    """
    raise NotImplementedError("PENDIENTE etapa 2: backoff(receive_count)")
