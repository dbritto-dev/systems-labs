"""Laboratorio message_queue_consumers: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
import random

from labs.message_queue_consumers.api import VISIBILITY, JobFailed, Message

HEARTBEAT = 0.5  # segundos entre latidos: bien dentro del timeout de visibilidad
MAX_RECEIVES = 4  # entregas antes de apartar un mensaje en la DLQ
BACKOFF_BASE = 1.0  # segundos antes de la 2.ª entrega; se duplica cada vez
BACKOFF_CAP = 8.0


class Consumer:
    def __init__(self, queue, dlq, handle, rng: random.Random | None = None) -> None:
        self.queue = queue
        self.dlq = dlq
        self.handle = handle
        self.rng = rng or random.Random(0)

    async def process(self, msg: Message) -> None:
        # Mantén el mensaje oculto mientras trabajas en él, tarde lo que tarde el trabajo.
        beat = asyncio.ensure_future(self.heartbeat(msg))
        try:
            await self.handle(msg)
        except JobFailed:
            beat.cancel()
            await self.on_failure(msg)
            return
        finally:
            beat.cancel()  # también cuando este proceso cae a mitad de trabajo
        await self.queue.delete(msg)  # confirma solo cuando el trabajo está hecho

    async def heartbeat(self, msg: Message) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT)
            if not await self.queue.change_visibility(msg, VISIBILITY):
                return  # ya no está, o ahora lo tiene otro

    async def on_failure(self, msg: Message) -> None:
        if msg.receive_count >= MAX_RECEIVES:  # sigue fallando: es veneno. Apártalo, que no estorbe.
            await self.dlq.send(msg)
            await self.queue.delete(msg)
        else:  # inténtalo más tarde, y cada vez más tarde
            await self.queue.change_visibility(msg, backoff(msg.receive_count, self.rng))


def backoff(receive_count: int, rng: random.Random | None = None) -> float:
    delay = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (receive_count - 1))
    return delay / 2 + (rng or random).uniform(0, delay / 2)  # equal jitter: nunca menos de la mitad
