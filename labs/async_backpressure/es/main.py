"""Laboratorio async_backpressure: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un proceso de ingesta: un flujo de eventos le empuja ~1,000 eventos/s (30% HIGH: pedidos, pagos;
70% LOW: clics, páginas vistas). Tu `Pipeline` los lee (la fuente), los analiza (etapa A), los
enriquece con un servicio (etapa B, ~25 ms por llamada) y los escribe en una base de datos por
lotes (etapa C). Cada evento que tienes cuesta memoria (4 KiB crudo, 8 analizado, 16
enriquecido); el contenedor tiene 256 MiB, y si los pasa el kernel mata el proceso (OOM): todo
evento que tenía se pierde, y uno nuevo arranca 5 s después. Mientras no lees, el origen guarda lo
que llega en su búfer (5,000 eventos, ~5 s); cuando se llena tira los más viejos, y nadie te avisa.

Ahora mismo las etapas se hablan con asyncio.Queue sin límite y escriben de 50 en 50. Cuando el
destino va lento (el primer incidente: autovacuum, 16 veces más lento) la cola de delante crece
sin límite, hasta que matan el proceso.

Haz las etapas en orden, en este archivo:

  Etapa 1  Colas acotadas: asyncio.Queue(maxsize=QUEUE_SIZE). Ahora `put` espera mientras la
           etapa siguiente va atrasada, así la lentitud viaja hacia atrás hasta la fuente, y la
           fuente deja de leer: guarda el origen en vez de tu memoria. No hay OOM. Pero una lentitud
           larga llena el búfer del origen (eventos perdidos, en silencio), y escribir de 50 en 50
           aprovecha menos de un tercio de lo que el destino lento podría aceptar.
  Etapa 2  Créditos, lotes adaptativos, descartes:
             - `Credits`: una ventana de permisos; cada etapa se los concede a la anterior, y solo
               los recupera cuando los eventos han seguido su camino (así acotan los eventos en la
               cola Y en manos de la etapa siguiente);
             - `take_batch`: espera un trozo y luego toma lo que ya hay en cola: los lotes crecen
               solos cuando el destino (o el servicio de enriquecimiento) va lento;
             - `Pipeline.admit`: cuando a la ventana le falta sitio, descarta los eventos LOW
               (contados, io.shed), y guarda los últimos RESERVE créditos para los HIGH: por esos
               la fuente espera.
           Después conéctalos en el Pipeline: los comentarios `# Etapa 2:` dicen dónde.

Lo que tienes (mira labs/async_backpressure/api.py):
  chunk = await io.read()         de 1 a 50 eventos del flujo (espera a la trama siguiente)
  parsed = io.parse(chunk)        RAW -> PARSED, sin E/S
  enriched = await io.enrich(b)   PARSED -> ENRICHED, como mucho ENRICH_MAX (100) eventos por llamada
  await io.write(batch)           al destino, como mucho MAX_BATCH (1,000) eventos ENRICHED;
                                  lanza SinkUnavailable cuando el destino está caído
  io.shed(events)                 descarta eventos LOW a propósito: contados, nunca en silencio
  Event(id, arrived, priority, kind), HIGH, LOW

Compruébalo:  LABS_LANG=es uv run pytest labs/async_backpressure
Mira una solución (¡después de intentarlo!):  labs/async_backpressure/es/reference.py
"""

from __future__ import annotations

import asyncio
from collections import deque  # etapa 2: quienes esperan en Credits

from labs.async_backpressure.api import (  # noqa: F401  (HIGH, LOW: etapa 2)
    ENRICH_MAX, HIGH, LOW, MAX_BATCH, Event, Services, SinkUnavailable,
)

BATCH = 50  # etapa 0: eventos por escritura, siempre
ENRICH_WORKERS = 8  # tareas que llaman al servicio de enriquecimiento (atiende 8 llamadas a la vez)
RETRY_DELAY = 0.5  # segundos entre dos intentos de una escritura mientras el destino está caído
QUEUE_SIZE = 20  # etapa 1: trozos que cabe en cada cola como mucho
WINDOW_A = 3_000  # etapa 2: eventos que el analizador concede a la fuente (crudos, 4 KiB cada uno)
WINDOW_B = 1_000  # etapa 2: eventos que los enriquecedores conceden al analizador: 8 llamadas de 100 y una cola
WINDOW_C = 2 * MAX_BATCH  # etapa 2: eventos que el escritor concede a los enriquecedores (un lote y otro)
RESERVE = 2_500  # etapa 2: los últimos créditos de WINDOW_A son solo para eventos HIGH


class Credits:
    """Etapa 2. Una ventana de permisos (créditos), contados en eventos: la etapa de después los
    concede, la de antes los gasta. Como un semáforo que toma n permisos de una vez, o el
    request(n) de reactive streams.

    Contrato:
      - `Credits(window)` empieza con `window` créditos libres; `self.free` es cuántos hay libres.
      - `try_take(n)`: toma n créditos ya si están libres (True); si no, no toma nada (False). Nunca
        tomes por delante de alguien que ya espera en `take`.
      - `await take(n)`: espera a que haya n créditos libres y tómalos. Se atiende a quien espera
        por orden de llegada. Pedir más que la ventana entera toma la ventana entera (si no,
        esperaría para siempre).
      - `grant(n)`: devuelve n créditos y despierta, en orden, a quienes les alcancen.

    Pista: guarda una deque de (n, futuro) que esperan. take: si try_take(n), vuelve; si no, añade
    (n, loop.create_future()) y espéralo. grant: free += n; mientras el n del primero quepa,
    sácalo con popleft, free -= n, fut.set_result(None) (sáltate un futuro ya resuelto: su tarea se
    canceló).
    """

    def __init__(self, window: int) -> None:
        self.window = window
        self.free = window
        self._waiters: deque[tuple[int, asyncio.Future]] = deque()

    def try_take(self, n: int) -> bool:
        raise NotImplementedError("PENDIENTE etapa 2: Credits.try_take(n)")

    async def take(self, n: int) -> None:
        raise NotImplementedError("PENDIENTE etapa 2: Credits.take(n)")

    def grant(self, n: int) -> None:
        raise NotImplementedError("PENDIENTE etapa 2: Credits.grant(n)")


async def take_batch(queue: asyncio.Queue, most: int) -> list[Event]:
    """Etapa 2. Un lote de una cola de trozos (listas de eventos): lotes adaptativos.

    Contrato:
      - Espera el primer trozo; después toma los trozos que ya están en cola, sin esperar, mientras
        el lote tenga menos de `most` eventos.
      - Devuelve como mucho `most` eventos; devuelve el resto del último trozo a la cola
        (`queue.put_nowait`).
      - Así, cuando el servicio siguiente va rápido los lotes son pequeños (poca latencia), y cuando
        va lento se acumulan más eventos durante cada llamada y el lote siguiente es más grande (más
        caudal): una escritura cuesta 15 ms + 0.1 ms por evento, así que 1,000 eventos cuestan
        115 ms, no 20 x 20 ms.

    Pista: batch = list(await queue.get()); while len(batch) < most and not queue.empty():
    batch += queue.get_nowait(). Luego, si es demasiado largo, devuelve batch[most:] y córtalo.
    """
    raise NotImplementedError("PENDIENTE etapa 2: take_batch(queue, most)")


async def write(io: Services, batch: list[Event]) -> None:
    """Escribe un lote, reintentando mientras el destino está caído: aquí nunca se tira un evento."""
    while True:
        try:
            await io.write(batch)
            return
        except SinkUnavailable:
            await asyncio.sleep(RETRY_DELAY)


class Pipeline:
    """Un proceso: fuente -> A (analizar) -> B (enriquecer, ENRICH_WORKERS tareas) -> C (escribir) -> el destino.

    Contrato:
      - `Pipeline(io)` se crea cada vez que el proceso arranca (también tras morir sin memoria), y
        `await pipeline.run()` lo ejecuta para siempre (arranca las etapas en un asyncio.TaskGroup).
      - Todo evento que lees acaba escrito en el destino, o descartado con io.shed() si es LOW.
      - La memoria queda bajo el 80% del límite; nada se pierde en silencio.
    """

    def __init__(self, io: Services) -> None:
        self.io = io
        # Etapa 1: asyncio.Queue(maxsize=QUEUE_SIZE) para cada una de las tres.
        # Etapa 2: otra vez asyncio.Queue() sin límite (los créditos las acotan), y además
        #          self.credits_a = Credits(WINDOW_A), self.credits_b = Credits(WINDOW_B),
        #          self.credits_c = Credits(WINDOW_C).
        self.to_a = asyncio.Queue()  # fuente -> A: trozos crudos
        self.to_b = asyncio.Queue()  # A -> B: trozos analizados
        self.to_c = asyncio.Queue()  # B -> C: trozos enriquecidos

    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.source())
            tg.create_task(self.parser())
            for _ in range(ENRICH_WORKERS):
                tg.create_task(self.enricher())
            tg.create_task(self.writer())

    def admit(self, chunk: list[Event]) -> list[Event]:
        """Etapa 2. Lo que la fuente deja entrar de un trozo leído; el resto se descarta.

        Contrato:
          - Eventos LOW solo mientras la ventana de la fuente tenga sitio más allá de la reserva:
            credits_a.free - len(chunk) >= RESERVE. Si no, descarta los LOW del trozo con
            self.io.shed(low) (contados: un descarte deliberado y visible) y devuelve solo los HIGH.
          - Los HIGH nunca se descartan: devuélvelos, y la fuente espera sus créditos (deja de leer;
            mientras, guarda el origen). La reserva es lo que los deja entrar mientras el destino
            está caído unos segundos.
        """
        raise NotImplementedError("PENDIENTE etapa 2: Pipeline.admit(chunk)")

    async def source(self) -> None:
        while True:
            chunk = await self.io.read()
            # Etapa 2: chunk = self.admit(chunk); si no está vacío, await
            #          self.credits_a.take(len(chunk)) y luego self.to_a.put_nowait(chunk).
            await self.to_a.put(chunk)  # nunca espera: una cola sin límite

    async def parser(self) -> None:
        while True:
            chunk = await self.to_a.get()
            parsed = self.io.parse(chunk)
            # Etapa 2: await self.credits_b.take(len(parsed)); self.to_b.put_nowait(parsed);
            #          después self.credits_a.grant(len(chunk)): el trozo ya siguió su camino.
            await self.to_b.put(parsed)

    async def enricher(self) -> None:
        while True:
            # Etapa 2: batch = await take_batch(self.to_b, ENRICH_MAX); tras la llamada,
            #          await self.credits_c.take(len(enriched)), put_nowait y
            #          self.credits_b.grant(len(batch)).
            batch = await self.to_b.get()
            enriched = await self.io.enrich(batch)
            await self.to_c.put(enriched)

    async def writer(self) -> None:
        while True:
            # Etapa 2: batch = await take_batch(self.to_c, MAX_BATCH), y tras escribir,
            #          self.credits_c.grant(len(batch)).
            batch = []
            while len(batch) < BATCH:  # siempre ~50 eventos, vaya lo lento que vaya el destino
                batch += await self.to_c.get()
            await write(self.io, batch)
