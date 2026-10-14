"""Laboratorio event_loop_blocking: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import asyncio

from labs.event_loop_blocking.api import CORES, Overloaded, ProcessPool, ThreadPool, now, report_lag

IO_THREADS = 16
CPU_PROCESSES = CORES
IO_QUEUE = 32
CPU_QUEUE = 2 * CORES
WATCH_EVERY = 0.1


class Service:
    def __init__(self) -> None:
        self.io = ThreadPool(IO_THREADS)  # E/S bloqueante: hilos que casi siempre esperan
        self.cpu = ProcessPool(CPU_PROCESSES)  # CPU: un proceso por núcleo, fuera del GIL
        self.watcher: asyncio.Task | None = None

    async def start(self) -> None:
        self.watcher = asyncio.create_task(self.watchdog())

    async def run_blocking(self, call):
        return await self.offload(call)

    async def offload(self, call):
        """Cada tipo de trabajo a su grupo acotado; una cola llena responde 503 ya, no un timeout luego."""
        pool, limit = (self.cpu, CPU_QUEUE) if call.cpu else (self.io, IO_QUEUE)
        if pool.waiting >= limit:
            raise Overloaded(f"{call.name}: {pool.waiting} llamadas ya en cola")
        return await pool.run(call)

    async def watchdog(self) -> None:
        """Lo tarde que el bucle nos despierta es lo que espera también cualquier otra tarea."""
        while True:
            t = now()
            await asyncio.sleep(WATCH_EVERY)
            report_lag(now() - t - WATCH_EVERY)
