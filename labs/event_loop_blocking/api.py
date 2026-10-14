"""What your Service gets: blocking calls, executors and the clock, on one event loop.

The service is one Python process. ONE event loop thread runs every request handler: while a handler
runs plain code, nothing else runs (no other request, no health check, no timer). Some handlers make
blocking calls: a sync DB driver (psycopg2), a sync HTTP client (requests), image resizing (Pillow),
a big json.dumps. Each one is a `Call`:

    call()                     run it right here, on the loop's thread: the WHOLE loop waits until it
                               returns (this is what every handler does today)
    call.cpu                   True for CPU work (resize, report), False for blocking I/O (db, http)
    call.name                  "db", "http", "resize" or "report"
    call.seconds               how long it takes on a free core, or with a free thread

    await to_thread(call)      like asyncio.to_thread: run it on the loop's default thread pool
                               (DEFAULT_THREADS threads, and a queue with no limit)
    ThreadPool(n)              a pool of n threads; `await pool.run(call)` runs a call on it
    ProcessPool(n)             a pool of n processes, on the machine's CORES cores
    pool.workers               its size
    pool.running               calls running on it now
    pool.waiting               calls queued on it, not started yet
    raise Overloaded(...)      from your Service: the handler answers 503 at once
    report_lag(seconds)        a metric: how late your watchdog woke up (the event loop's lag)
    now()                      the clock, in seconds

Threads and the GIL. A thread waiting on blocking I/O releases the GIL: 32 threads can wait for 32
slow database queries at once. A thread doing CPU work holds the GIL: however many threads you have,
only one runs Python code at a time, and the loop's own thread must take turns with it (the loop
runs about GIL_SHARE times slower while one computes). Processes have their own interpreter and
GIL: CPU work runs on CORES cores in parallel, but sending a call to a process pickles it, which
costs PICKLE seconds on the loop.

It all runs on virtual time: a blocking call moves the loop's clock forward without letting anything
else run, exactly like a real one; pools and their threads are simulated, not real.
"""

from __future__ import annotations

import asyncio
import heapq
import weakref
from collections import deque
from collections.abc import Callable

from core.vtime import now

CORES = 4  # cores the machine gives the process pools
DEFAULT_THREADS = min(32, CORES + 4)  # asyncio's default executor: ThreadPoolExecutor()
PICKLE = 0.001  # seconds of loop time to send one call to a process (pickling its arguments)
GIL_SHARE = 2.0  # the loop runs this many times slower while a thread computes (they share the GIL)

__all__ = ["CORES", "Call", "DEFAULT_THREADS", "GIL_SHARE", "Overloaded", "PICKLE", "ProcessPool",
           "ThreadPool", "now", "report_lag", "to_thread"]


class Overloaded(Exception):
    """Raise it from your Service to refuse a request: the handler answers 503 at once (and the user's
    client retries later), instead of queueing work it cannot finish in time."""


class Runtime:
    """The process: its GIL, the machine's cores, its pools and what it reports. The scenario installs
    one per event loop and gets told about every blocking call, every call a pool runs and every lag
    report; a test that does not install one gets a quiet default."""

    def __init__(self, on_block: Callable | None = None, on_call: Callable | None = None,
                 on_report: Callable | None = None) -> None:
        self.on_block = on_block  # (t0, seconds, gil_extra, cause)
        self.on_call = on_call  # (submitted, started, ran, ended, pool id, worker, call)
        self.on_report = on_report  # (t, seconds)
        self.gil_free = 0.0  # when the last CPU work queued for the GIL is done
        self.cores = [0.0] * CORES  # when each core is next free (a heap)
        self.pools: list[_Pool] = []  # pools of this process, in the order they were made
        self.default: ThreadPool | None = None  # the loop's default executor, made on first use
        self.reports: list[tuple[float, float]] = []  # (t, lag) when nobody listens
        self.dead = False  # killed: what is left of it runs no more code (a new one clears it)

    def reset(self, t: float) -> None:
        """The process died: its pools and the work in them are gone."""
        for pool in self.pools:
            pool.dead = True
        self.dead = True
        self.pools, self.default = [], None
        self.gil_free = t
        self.cores = [t] * CORES

    def snapshot(self) -> tuple:
        """(process, workers, running, waiting, default) for each pool, in order."""
        return tuple((p.process, p.workers, p.running, len(p.queue), p is self.default) for p in self.pools)


_RUNTIMES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def install(loop: asyncio.AbstractEventLoop, rt: Runtime) -> None:
    _RUNTIMES[loop] = rt


def runtime() -> Runtime:
    loop = asyncio.get_running_loop()
    rt = _RUNTIMES.get(loop)
    if rt is None:
        rt = _RUNTIMES[loop] = Runtime()
    return rt


def block(seconds: float, cause: str = "own") -> None:
    """Run `seconds` of plain code on the loop's thread: the virtual clock jumps forward and nothing
    else runs meanwhile (no other task, no timer). While a thread computes, the loop shares the GIL
    with it and the same code takes GIL_SHARE times longer."""
    loop = asyncio.get_running_loop()
    rt = runtime()
    if rt.dead:
        return  # the process was killed: it runs nothing more
    t0 = loop.time()
    extra = seconds * (GIL_SHARE - 1.0) if rt.gil_free > t0 else 0.0
    loop._now = t0 + seconds + extra  # the virtual clock (core.vtime.VirtualClockLoop)
    if rt.on_block is not None:
        rt.on_block(t0, seconds, extra, cause)


class Call:
    """One blocking call a handler has to make. `call()` runs it on the current thread."""

    __slots__ = ("name", "seconds", "cpu", "result")

    def __init__(self, name: str, seconds: float, cpu: bool, result: object = None) -> None:
        self.name, self.seconds, self.cpu, self.result = name, seconds, cpu, result

    def __call__(self):
        block(self.seconds, self.name)
        return self.result

    def __repr__(self) -> str:
        return f"Call({self.name!r}, {self.seconds * 1000:.0f} ms, cpu={self.cpu})"


class _Pool:
    """A pool of workers with a FIFO queue (concurrent.futures' executors). No limit on the queue."""

    process = False

    def __init__(self, workers: int) -> None:
        if int(workers) < 1:
            raise ValueError(f"a pool needs at least 1 worker, not {workers!r}")
        self.workers = int(workers)
        self.rt: Runtime | None = None
        self.dead = False
        self.id = -1
        self._fresh()
        try:
            self._bind()  # made inside the service (a running loop): it shows from the start
        except RuntimeError:
            pass  # no running loop yet: it binds on its first call

    def _fresh(self) -> None:
        self.running = 0
        self.queue: deque[tuple[asyncio.Future, Call, float]] = deque()
        self.free = list(range(self.workers - 1, -1, -1))  # worker ids, the lowest first

    def _bind(self) -> Runtime:
        rt = runtime()
        if self.rt is not rt or self.dead:  # first use, or the process restarted under it
            self.rt, self.dead = rt, False
            self._fresh()
            self.id = len(rt.pools)
            rt.pools.append(self)
        return rt

    @property
    def waiting(self) -> int:
        """Calls queued, not started yet."""
        return len(self.queue)

    async def run(self, call: Call):
        """Run `call` on a worker of this pool and return its result. It waits in the queue while every
        worker is busy."""
        self._bind()
        if self.process:
            block(PICKLE, "pickle")  # the loop pickles the call to send it to a process
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        item = (fut, call, loop.time())
        self.queue.append(item)
        self._dispatch(loop.time())
        try:
            return await fut
        except asyncio.CancelledError:
            if item in self.queue:  # not started: it leaves the queue (a started one runs to the end)
                self.queue.remove(item)
            raise

    def _begin(self, start: float, call: Call) -> float:
        """When the call really runs, once a worker has it at `start`."""
        return start

    def _dispatch(self, t: float) -> None:
        loop = asyncio.get_running_loop()
        while self.running < self.workers and self.queue:
            fut, call, submitted = self.queue.popleft()
            if fut.done():
                continue
            start = max(t, submitted)
            ran = self._begin(start, call)
            end = ran + call.seconds
            worker = self.free.pop()
            self.running += 1
            loop.call_at(end, self._done, fut, call, worker, end)
            if self.rt.on_call is not None:
                self.rt.on_call(submitted, start, ran, end, self.id, worker, call)

    def _done(self, fut: asyncio.Future, call: Call, worker: int, end: float) -> None:
        if self.dead:
            return
        self.running -= 1
        self.free.append(worker)
        if not fut.done():
            fut.set_result(call.result)
        self._dispatch(end)  # the worker has been free since `end`, even if the loop hears it late

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.workers}, running={self.running}, waiting={self.waiting})"


class ThreadPool(_Pool):
    """n threads (concurrent.futures.ThreadPoolExecutor). Blocking I/O runs in parallel; CPU work takes
    turns on the GIL, one call at a time for the whole process."""

    def _begin(self, start: float, call: Call) -> float:
        if not call.cpu:
            return start
        rt = self.rt
        ran = max(start, rt.gil_free)
        rt.gil_free = ran + call.seconds
        return ran


class ProcessPool(_Pool):
    """n processes (concurrent.futures.ProcessPoolExecutor): each has its own GIL, and they share the
    machine's CORES cores. Each call costs PICKLE seconds on the loop to send."""

    process = True

    def _begin(self, start: float, call: Call) -> float:
        cores = self.rt.cores
        ran = max(start, heapq.heappop(cores))
        heapq.heappush(cores, ran + call.seconds)
        return ran


async def to_thread(call: Call):
    """asyncio.to_thread(call): run it on the loop's default thread pool (DEFAULT_THREADS threads, no
    limit on its queue) and return its result."""
    rt = runtime()
    if rt.default is None or rt.default.dead:
        rt.default = ThreadPool(DEFAULT_THREADS)
    return await rt.default.run(call)


def report_lag(seconds: float) -> None:
    """Send the event loop's lag to your metrics (a gauge): how late a timer ran, in seconds."""
    rt = runtime()
    if rt.on_report is not None:
        rt.on_report(now(), float(seconds))
    else:
        rt.reports.append((now(), float(seconds)))
