"""Laboratorio async_backpressure: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import asyncio
from collections import deque

from labs.async_backpressure.api import ENRICH_MAX, HIGH, LOW, MAX_BATCH, Event, Services, SinkUnavailable

BATCH = 50  # etapa 0: eventos por escritura, siempre
ENRICH_WORKERS = 8  # tareas que llaman al servicio de enriquecimiento (atiende 8 llamadas a la vez)
RETRY_DELAY = 0.5  # segundos entre dos intentos de una escritura mientras el destino está caído
QUEUE_SIZE = 20  # etapa 1: trozos que cabe en cada cola como mucho
WINDOW_A = 3_000  # etapa 2: eventos que el analizador concede a la fuente (crudos, 4 KiB cada uno)
WINDOW_B = 1_000  # etapa 2: eventos que los enriquecedores conceden al analizador: 8 llamadas de 100 y una cola
WINDOW_C = 2 * MAX_BATCH  # etapa 2: eventos que el escritor concede a los enriquecedores (un lote y otro)
RESERVE = 2_500  # etapa 2: los últimos créditos de WINDOW_A son solo para eventos HIGH


class Credits:
    def __init__(self, window: int) -> None:
        self.window = window
        self.free = window
        self._waiters: deque[tuple[int, asyncio.Future]] = deque()

    def try_take(self, n: int) -> bool:
        if self._waiters or self.free < n:
            return False  # nunca pases por delante de quien ya espera
        self.free -= n
        return True

    async def take(self, n: int) -> None:
        n = min(n, self.window)  # más que la ventana entera esperaría para siempre
        if self.try_take(n):
            return
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append((n, fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.grant(n)  # concedido justo al cancelarnos: devuélvelo
            elif (n, fut) in self._waiters:
                self._waiters.remove((n, fut))
            raise

    def grant(self, n: int) -> None:
        self.free += n
        while self._waiters and self._waiters[0][0] <= self.free:
            k, fut = self._waiters.popleft()
            if not fut.done():  # sáltate a quien se canceló
                self.free -= k
                fut.set_result(None)


async def take_batch(queue: asyncio.Queue, most: int) -> list[Event]:
    batch = list(await queue.get())  # espera el primer trozo ...
    while len(batch) < most and not queue.empty():  # ... y toma lo que ya hay, sin esperar
        batch += queue.get_nowait()
    if len(batch) > most:
        queue.put_nowait(batch[most:])  # el resto espera al lote siguiente
        del batch[most:]
    return batch


async def write(io: Services, batch: list[Event]) -> None:
    """Escribe un lote, reintentando mientras el destino está caído: aquí nunca se tira un evento."""
    while True:
        try:
            await io.write(batch)
            return
        except SinkUnavailable:
            await asyncio.sleep(RETRY_DELAY)


class Pipeline:
    def __init__(self, io: Services) -> None:
        self.io = io
        # Los créditos acotan cada evento entre dos etapas, en la cola y en manos de la etapa que lo
        # tiene, así la memoria tiene techo: 3,000 x 4 + 1,000 x 8 + 2,000 x 16 KiB = ~51 MiB.
        self.to_a, self.to_b, self.to_c = asyncio.Queue(), asyncio.Queue(), asyncio.Queue()
        self.credits_a = Credits(WINDOW_A)
        self.credits_b = Credits(WINDOW_B)
        self.credits_c = Credits(WINDOW_C)

    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.source())
            tg.create_task(self.parser())
            for _ in range(ENRICH_WORKERS):
                tg.create_task(self.enricher())
            tg.create_task(self.writer())

    def admit(self, chunk: list[Event]) -> list[Event]:
        # Eventos LOW solo mientras la ventana tenga sitio más allá de la reserva; si no, se
        # descartan, contados. Los HIGH siempre entran: la fuente espera sus créditos (mientras,
        # guarda el origen), y la reserva es lo que los deja entrar durante una caída.
        low = [e for e in chunk if e.priority == LOW]
        if low and self.credits_a.free - len(chunk) < RESERVE:
            self.io.shed(low)
            return [e for e in chunk if e.priority == HIGH]
        return chunk

    async def source(self) -> None:
        while True:
            chunk = self.admit(await self.io.read())
            if chunk:
                await self.credits_a.take(len(chunk))
                self.to_a.put_nowait(chunk)

    async def parser(self) -> None:
        while True:
            chunk = await self.to_a.get()
            parsed = self.io.parse(chunk)
            await self.credits_b.take(len(parsed))
            self.to_b.put_nowait(parsed)
            self.credits_a.grant(len(chunk))

    async def enricher(self) -> None:
        while True:
            batch = await take_batch(self.to_b, ENRICH_MAX)  # llamadas más grandes cuando el servicio va lento
            enriched = await self.io.enrich(batch)
            await self.credits_c.take(len(enriched))
            self.to_c.put_nowait(enriched)
            self.credits_b.grant(len(batch))

    async def writer(self) -> None:
        while True:
            batch = await take_batch(self.to_c, MAX_BATCH)  # escrituras más grandes cuando el destino va lento
            await write(self.io, batch)
            self.credits_c.grant(len(batch))
