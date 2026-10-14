"""Lab event_loop_blocking: YOUR FILE. Edit it and save; the live window reruns it.

An asyncio web service handles ~100 requests/s on ONE event loop. Most requests are light (an
async DB query, a little JSON). Some make blocking calls: a sync DB driver, a sync HTTP client to a
partner API, image resizing on upload (CPU), a big json.dumps for a report export (CPU). Every
handler runs its blocking calls through your `Service.run_blocking(call)`, and today that just calls
`call()` on the loop's thread: for those milliseconds the WHOLE loop stops. No other request runs,
no timer fires, and the load balancer's health check (every 2 s, 1 s timeout) waits too. Three
failed checks in a row and the orchestrator kills the instance: 10 s of 503s while it restarts.

At random times, like in production: a big batch of UPLOADS makes resizing slow, a sync dependency
gets SLOW (a database lock, a partner API), a burst of REPORTS asks for heavy exports, or the
garbage collector PAUSES the process. The first incident is always an upload batch at 0:20.

Do the stages in order, in this file:

  Stage 1  Offload: `await to_thread(call)` instead of `call()`. The loop stays free, but every
           call goes to the default pool: 8 threads, one GIL for the CPU work, no limit on its queue.
  Stage 2  Bound it: CPU work to a ProcessPool (one process per core), blocking I/O to its own
           ThreadPool, each with a queue limit: when it is full, raise Overloaded (a 503 now beats a
           timeout later). And a watchdog that measures the loop's lag and reports it.

What you get (see labs/event_loop_blocking/api.py):
  call()                     run a blocking call right here: the whole loop waits
  call.cpu, call.name        CPU work (resize, report) or blocking I/O (db, http)
  await to_thread(call)      the loop's default thread pool (DEFAULT_THREADS threads, no queue limit)
  ThreadPool(n), ProcessPool(n), await pool.run(call), pool.waiting, pool.running
  raise Overloaded(...)      the handler answers 503 at once
  report_lag(seconds), now()

Check yourself:  uv run pytest labs/event_loop_blocking
Peek at a solution (after trying!):  labs/event_loop_blocking/reference.py
"""

from __future__ import annotations

import asyncio  # noqa: F401  (stage 2: asyncio.create_task, asyncio.sleep)

from labs.event_loop_blocking.api import CORES, Overloaded, ProcessPool, ThreadPool, now, report_lag, to_thread  # noqa: F401

IO_THREADS = 16  # stage 2: threads for blocking I/O (they mostly wait on the network, not on the GIL)
CPU_PROCESSES = CORES  # stage 2: processes for CPU work: one per core (more would only take turns)
IO_QUEUE = 32  # stage 2: blocking I/O calls allowed to wait for a thread; one more gets a 503
CPU_QUEUE = 2 * CORES  # stage 2: CPU calls allowed to wait for a process
WATCH_EVERY = 0.1  # stage 2: seconds between two looks of the watchdog


class Service:
    """The web service's plumbing for blocking calls. The scenario makes one per process start (a
    restart after a kill makes a new one) and awaits `start()` before any request.

    Contract:
      - `await run_blocking(call)` runs one blocking call for a handler and returns its result. It may
        raise Overloaded: that request is answered 503 at once.
      - Nothing in the event loop's thread may take long: a health check that waits more than 1 s
        fails, and three in a row kill the instance.
    """

    def __init__(self) -> None:
        # Stage 2: self.io = ThreadPool(IO_THREADS) and self.cpu = ProcessPool(CPU_PROCESSES).
        self.io = None
        self.cpu = None
        self.watcher = None  # stage 2: the watchdog's task

    async def start(self) -> None:
        # Stage 2: start the watchdog in the background: self.watcher = asyncio.create_task(self.watchdog())
        pass

    async def run_blocking(self, call):
        # Stage 1: return await to_thread(call)
        #
        # Stage 2: return await self.offload(call)
        return call()

    async def offload(self, call):
        """Stage 2. Run the call on the pool made for its kind of work, or refuse it at once.

        CPU work (call.cpu) goes to self.cpu, a process per core: each process has its own GIL, so 4
        resizes run at once. Blocking I/O goes to self.io: its threads spend their time waiting on
        the network, so many of them fit. Two pools are also two bulkheads: a slow database fills the
        I/O pool, not the one resizing images.

        Bound each queue: if that pool already has CPU_QUEUE (for CPU) or IO_QUEUE (for I/O) calls
        waiting, `raise Overloaded(...)`. Without a bound, during a burst the queue grows for as long
        as the burst lasts, every call in it waits longer than the user does (who has gone after 5 s),
        and the pool still does all that work for nobody.

        Hint: pool, limit = (self.cpu, CPU_QUEUE) if call.cpu else (self.io, IO_QUEUE); if
        pool.waiting >= limit: raise Overloaded(call.name); return await pool.run(call).
        """
        raise NotImplementedError("TODO stage 2: Service.offload(call)")

    async def watchdog(self) -> None:
        """Stage 2. Measure the event loop's lag forever, and report it.

        Ask the loop to wake you up in WATCH_EVERY seconds and see how late it does: that delay is
        how long every callback waits right now, because something holds the loop (a blocking call,
        a garbage collection). Report it with report_lag(seconds), like a gauge in your metrics: it
        is the first number to look at when "everything is slow and the CPU is not even busy".

        Hint: while True: t = now(); await asyncio.sleep(WATCH_EVERY);
        report_lag(now() - t - WATCH_EVERY).
        """
        raise NotImplementedError("TODO stage 2: Service.watchdog()")
