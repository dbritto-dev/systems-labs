"""Laboratorio event_loop_blocking: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un servicio web asyncio atiende ~100 peticiones/s con UN solo bucle de eventos. Casi todas las
peticiones son ligeras (una consulta async a la BD, un poco de JSON). Algunas hacen llamadas
bloqueantes: un driver síncrono de BD, un cliente HTTP síncrono hacia la API de un socio, redimensionar
la imagen de una subida (CPU), un json.dumps enorme para exportar un informe (CPU). Cada manejador
pasa sus llamadas bloqueantes por tu `Service.run_blocking(call)`, que hoy solo hace `call()` en el
hilo del bucle: durante esos milisegundos el bucle ENTERO se para. No corre ninguna otra petición, no
salta ningún temporizador, y el chequeo de salud del balanceador (cada 2 s, timeout de 1 s) también
espera. Tres chequeos fallidos seguidos y el orquestador mata la instancia: 10 s de 503 mientras
reinicia.

De vez en cuando, como en producción: un gran lote de FOTOS hace lento el redimensionado, una
dependencia síncrona va LENTA (un bloqueo en la base de datos, la API de un socio), una ráfaga de
INFORMES pide exportaciones pesadas, o el recolector de basura PAUSA el proceso. El primer incidente
es siempre un lote de fotos a la 0:20.

Haz las etapas en orden, en este archivo:

  Etapa 1  Delega: `await to_thread(call)` en vez de `call()`. El bucle queda libre, pero toda
           llamada va al pool por defecto: 8 hilos, un solo GIL para la CPU, una cola sin límite.
  Etapa 2  Acótalo: la CPU a un ProcessPool (un proceso por núcleo), la E/S bloqueante a su propio
           ThreadPool, cada uno con un límite de cola: si está llena, lanza Overloaded (un 503 ahora
           es mejor que un timeout después). Y un vigilante que mide el retardo del bucle y lo publica.

Lo que tienes (mira labs/event_loop_blocking/api.py):
  call()                     ejecuta aquí mismo una llamada bloqueante: todo el bucle espera
  call.cpu, call.name        trabajo de CPU (resize, report) o E/S bloqueante (db, http)
  await to_thread(call)      el pool de hilos por defecto del bucle (DEFAULT_THREADS hilos, cola sin límite)
  ThreadPool(n), ProcessPool(n), await pool.run(call), pool.waiting, pool.running
  raise Overloaded(...)      el manejador responde 503 al instante
  report_lag(seconds), now()

Compruébalo:  LABS_LANG=es uv run pytest labs/event_loop_blocking
Mira una solución (¡después de intentarlo!):  labs/event_loop_blocking/es/reference.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (etapa 2: asyncio.create_task, asyncio.sleep)

from labs.event_loop_blocking.api import CORES, Overloaded, ProcessPool, ThreadPool, now, report_lag, to_thread  # noqa: F401

IO_THREADS = 16  # etapa 2: hilos para E/S bloqueante (casi siempre esperan a la red, no al GIL)
CPU_PROCESSES = CORES  # etapa 2: procesos para la CPU: uno por núcleo (más solo se turnarían)
IO_QUEUE = 32  # etapa 2: llamadas de E/S que pueden esperar un hilo; una más recibe un 503
CPU_QUEUE = 2 * CORES  # etapa 2: llamadas de CPU que pueden esperar un proceso
WATCH_EVERY = 0.1  # etapa 2: segundos entre dos miradas del vigilante


class Service:
    """La fontanería del servicio web para las llamadas bloqueantes. El escenario crea uno en cada
    arranque del proceso (un reinicio tras matarlo crea otro) y espera a `start()` antes de cualquier
    petición.

    Contrato:
      - `await run_blocking(call)` ejecuta una llamada bloqueante de un manejador y devuelve su
        resultado. Puede lanzar Overloaded: esa petición recibe un 503 al instante.
      - Nada en el hilo del bucle de eventos puede tardar: un chequeo de salud que espera más de 1 s
        falla, y tres seguidos matan la instancia.
    """

    def __init__(self) -> None:
        # Etapa 2: self.io = ThreadPool(IO_THREADS) y self.cpu = ProcessPool(CPU_PROCESSES).
        self.io = None
        self.cpu = None
        self.watcher = None  # etapa 2: la tarea del vigilante

    async def start(self) -> None:
        # Etapa 2: arranca el vigilante en segundo plano: self.watcher = asyncio.create_task(self.watchdog())
        pass

    async def run_blocking(self, call):
        # Etapa 1: return await to_thread(call)
        #
        # Etapa 2: return await self.offload(call)
        return call()

    async def offload(self, call):
        """Etapa 2. Ejecuta la llamada en el pool hecho para su tipo de trabajo, o recházala al instante.

        La CPU (call.cpu) va a self.cpu, un proceso por núcleo: cada proceso tiene su propio GIL, así
        que 4 redimensionados corren a la vez. La E/S bloqueante va a self.io: sus hilos pasan el
        tiempo esperando a la red, así que caben muchos. Dos pools son también dos
        bulkheads: una base de datos lenta llena el pool de E/S, no el que redimensiona imágenes.

        Acota cada cola: si ese pool ya tiene CPU_QUEUE (para CPU) o IO_QUEUE (para E/S) llamadas
        esperando, `raise Overloaded(...)`. Sin límite, en una ráfaga la cola crece mientras dure,
        cada llamada en ella espera más que el usuario (que se va a los 5 s), y el pool hace igual
        todo ese trabajo para nadie.

        Pista: pool, limit = (self.cpu, CPU_QUEUE) if call.cpu else (self.io, IO_QUEUE); if
        pool.waiting >= limit: raise Overloaded(call.name); return await pool.run(call).
        """
        raise NotImplementedError("PENDIENTE etapa 2: Service.offload(call)")

    async def watchdog(self) -> None:
        """Etapa 2. Mide el retardo del bucle de eventos para siempre, y publícalo.

        Pide al bucle que te despierte en WATCH_EVERY segundos y mira cuánto tarde lo hace: ese
        retraso es lo que espera ahora mismo cada tarea, porque algo retiene el bucle (una llamada
        bloqueante, una recolección de basura). Publícalo con report_lag(seconds), como un indicador
        en tus métricas: es el primer número que mirar cuando "todo va lento y la CPU ni está ocupada".

        Pista: while True: t = now(); await asyncio.sleep(WATCH_EVERY);
        report_lag(now() - t - WATCH_EVERY).
        """
        raise NotImplementedError("PENDIENTE etapa 2: Service.watchdog()")
