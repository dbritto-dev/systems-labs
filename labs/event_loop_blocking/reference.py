"""Lab event_loop_blocking: a working solution. Read it after you have tried main.py."""

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
        self.io = ThreadPool(IO_THREADS)  # blocking I/O: threads that mostly wait
        self.cpu = ProcessPool(CPU_PROCESSES)  # CPU work: one process per core, out of the GIL
        self.watcher: asyncio.Task | None = None

    async def start(self) -> None:
        self.watcher = asyncio.create_task(self.watchdog())

    async def run_blocking(self, call):
        return await self.offload(call)

    async def offload(self, call):
        """Each kind of work to its own bounded pool; a full queue answers 503 now, not a timeout later."""
        pool, limit = (self.cpu, CPU_QUEUE) if call.cpu else (self.io, IO_QUEUE)
        if pool.waiting >= limit:
            raise Overloaded(f"{call.name}: {pool.waiting} calls already queued")
        return await pool.run(call)

    async def watchdog(self) -> None:
        """How late the loop wakes us up is how long every other callback waits too."""
        while True:
            t = now()
            await asyncio.sleep(WATCH_EVERY)
            report_lag(now() - t - WATCH_EVERY)

