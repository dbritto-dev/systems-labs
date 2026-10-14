"""Lab event_loop_blocking: one endless run on virtual time, handed out a minute at a time.

Users send ~`rate` requests/s (the rate drifts like real traffic) to one asyncio web service: one
process, ONE event loop. 82% are light (parse, an async DB query, render). The rest make one
blocking call through your `Service.run_blocking(call)`: a sync DB driver (8%, ~10 ms), a sync HTTP
client to a partner API (4%, ~30 ms), an image resize on upload (4%, ~40 ms of CPU) or a report
export's big json.dumps (2%, ~30 ms of CPU). A user gives up after 5 s (a 504); the handler does
not notice and goes on (most frameworks do not cancel it).

The load balancer checks /health every 2 s and gives it 1 s; after 3 failures in a row the
orchestrator kills the process and starts a new one, which takes 10 s (meanwhile: 503s). Everything
the process held is lost: the requests in flight, its pools and their queues.

Incidents come at random, like in production: an upload batch (a wedding photographer, a catalogue
import: more uploads, much bigger images, 4.6-6 cores of resizing), a slow dependency (a lock in the
database, a partner API degrading: sync calls 30-80x slower), a burst of report exports (month end, a
dashboard every open tab refreshes: 4.5-6 cores of json.dumps) or garbage-collection pauses (a cache
refill allocates millions of objects: the whole process stops 18-36 ms, again and again). The first
incident is always an upload batch at 0:20-0:50.

The loop's lag is measured from outside your code (like an APM agent): a timer every 50 ms, and how
late it runs. The run never restarts: the process, its queues and the clock carry on from minute to
minute.
"""

from __future__ import annotations

import asyncio
import contextvars
import itertools
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.incidents import Kind, Planned, rate_at, schedule
from core.vtime import VirtualRun, now
from labs.event_loop_blocking import api
from labs.event_loop_blocking.api import Call, Overloaded, block

LAB = "event_loop_blocking"
NAMES = ("Service",)
PIECE = 60.0
TIMEOUT = 5.0  # a user gives up after this long (a 504)
DRAIN = TIMEOUT + 1.0  # simulate this far past a minute before handing it out: every request has ended
HC_EVERY = 2.0  # the load balancer's health check: every 2 s ...
HC_TIMEOUT = 1.0  # ... answered within 1 s ...
HC_FAILS = 3  # ... or after 3 failures in a row the process is killed
RESTART = 10.0  # seconds a new process takes to start and pass its first check
HC_CPU = 0.0002  # the /health handler's own work
PROBE = 0.05  # the lag probe's period (outside your code, like an APM agent)
SAMPLE = 0.25  # how often the pools are recorded
BIG = 0.005  # loop stalls at least this long are kept one by one (for the pictures)

# Routes: light requests, then the four kinds of blocking call.
LIGHT, DB, HTTP, RESIZE, REPORT = range(5)
ROUTE_NAMES = ("light", "db", "http", "resize", "report")
MIX = (0.82, 0.08, 0.04, 0.04, 0.02)  # share of the traffic on a normal day
SECONDS = (0.0, 0.010, 0.030, 0.040, 0.030)  # a blocking call's usual time (±50%)
CPU = (False, False, False, True, True)  # CPU work (else blocking I/O)
PARSE, RENDER = 0.0003, 0.0005  # every handler's own work on the loop
ASYNC_DB = (0.003, 0.010)  # a light request's async DB query (it awaits: the loop runs others)
UPLOAD_RATE = 3.0  # an upload batch: this many times more uploads, each much bigger
REPORT_RATE = 6.0  # a report burst: this many times more exports, each much bigger
PEAK = 1.45  # a bound on the traffic (as a share of `rate`), for thinning
GC_GAP = (0.4, 1.0)  # seconds between two collections during a GC incident

# Outcomes of a request.
OK, SHED, TIMED_OUT, KILLED, DOWN = range(5)
# Loop time, per second, by what held it: its own work, blocking I/O, CPU, the GIL, garbage collection.
OWN, IO, CPU_COL, GIL, GC = range(5)
CAUSE_COL = {"own": OWN, "pickle": OWN, "db": IO, "http": IO, "resize": CPU_COL, "report": CPU_COL, "gc": GC}

# Which process a task belongs to: tasks the service makes inherit it, and a kill cancels them all.
PROC: contextvars.ContextVar[int | None] = contextvars.ContextVar("event_loop_blocking_proc", default=None)

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 50.0, "uploads", 5.0, "wedding_photos")
KINDS = [
    Kind("uploads", 0.3, median=40.0, shortest=30.0, longest=60.0, severity=(4.6, 6.0), causes=(
        "wedding_photos", "catalogue_import", "camera_roll_sync", "photo_migration")),
    Kind("slow_dep", 0.3, median=35.0, shortest=25.0, longest=55.0, severity=(30.0, 80.0), causes=(
        "db_lock", "partner_api", "dns_resolver", "db_failover")),
    Kind("reports", 0.25, median=30.0, shortest=20.0, longest=45.0, severity=(4.5, 6.0), causes=(
        "month_end", "dashboard_refresh", "partner_export", "scraper")),
    Kind("gc", 0.15, median=30.0, shortest=20.0, longest=45.0, severity=(0.018, 0.030), causes=(
        "cache_refill", "big_import", "memory_leak", "cgroup_throttle")),
]
MEAN_GAP = 40.0
QUIET = 30.0  # calm after an incident: it is judged (and the queues drain) before the next one


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


class Req:
    __slots__ = ("id", "start", "route", "done")

    def __init__(self, rid: int, start: float, route: int) -> None:
        self.id, self.start, self.route, self.done = rid, start, route, False


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.work_rng = random.Random(seed * 17 + 3)  # how long each call takes
        self.rt = api.Runtime(on_block=self.on_block, on_call=self.on_call, on_report=self.on_report)
        self.service = None
        self.gen = 0  # processes started so far
        self.ctx = contextvars.Context()  # the running process's context (PROC = its number)
        self.alive = False
        self.up_since = 0.0
        self.kill_at: float | None = None
        self.up_at = 0.0
        self.ids = itertools.count()
        self.inflight: dict[int, Req] = {}
        self.hcs: deque[list] = deque()  # health checks sent, oldest first: [sent, answered or None]
        self.fails = 0  # failed health checks in a row
        self.next_hc = HC_EVERY  # when the load balancer sends its next health check
        self.planned: list[Planned] = []
        self.bugs: list[BaseException] = []
        self.secs: dict[int, list[float]] = {}  # loop time per second, by cause
        # Tables.
        self.requests: list[tuple] = []  # (id, start, end, route, ok, outcome)
        self.health: list[tuple] = []  # (sent, end, ok)
        self.lags: list[tuple] = []  # (t, lag): the probe
        self.reports: list[tuple] = []  # (t, lag): your watchdog
        self.blocks: list[tuple] = []  # (t0, t1, cause): every stall of the loop of BIG or more
        self.calls: list[tuple] = []  # (submitted, started, ran, ended, pool, worker, name)
        self.samples: list[tuple] = []  # (t, alive, waiting, running, pools, in flight)
        self.kills: list[tuple] = []  # (t, back)

    # ---------------------------------------------------------------- the runtime tells us

    def on_block(self, t0: float, seconds: float, extra: float, cause: str) -> None:
        self._spread(t0, seconds, CAUSE_COL.get(cause, OWN))
        if extra:
            self._spread(t0 + seconds, extra, GIL)
        if seconds + extra >= BIG:
            self.blocks.append((round(t0, 5), round(t0 + seconds + extra, 5), cause))
        if self.alive:
            self.sweep(t0 + seconds + extra)  # the orchestrator does not wait for the loop: a kill lands mid-call

    def _spread(self, t0: float, dur: float, col: int) -> None:
        t, end = t0, t0 + dur
        while t < end:
            s = int(t)
            nxt = min(end, s + 1.0)
            row = self.secs.get(s)
            if row is None:
                row = self.secs[s] = [0.0] * 5
            row[col] += nxt - t
            t = nxt

    def on_call(self, submitted, started, ran, ended, pool, worker, call) -> None:
        self.calls.append((round(submitted, 5), round(started, 5), round(ran, 5), round(ended, 5), pool, worker,
                           call.name))

    def on_report(self, t: float, lag: float) -> None:
        if self.alive:
            self.reports.append((round(t, 4), lag))

    # ---------------------------------------------------------------- the process

    def spawn(self, coro) -> asyncio.Task:
        """One of the scenario's own tasks (users, the load balancer, the probe): no process owns it."""
        return asyncio.get_running_loop().create_task(coro, context=contextvars.Context())

    def run_in_process(self, coro) -> asyncio.Task:
        """A task of the running process: it dies with it."""
        return asyncio.get_running_loop().create_task(coro, context=self.ctx.copy())

    async def boot(self, at: float) -> None:
        """A process starts: a new Service, started before it takes requests."""
        await asyncio.sleep(max(0.0, at - now()))
        self.gen += 1
        PROC.set(self.gen)  # this task, and every task the service makes from here, belong to it
        self.ctx = contextvars.copy_context()
        self.alive, self.up_since, self.fails = True, now(), 0
        self.rt.dead = False
        try:
            self.service = self.code.Service()
            await self.service.start()
        except Exception as exc:  # noqa: BLE001 - a bug in the code under test: surface it
            self.bugs.append(exc)

    def is_down(self, t: float) -> bool:
        return self.kill_at is not None and self.kill_at <= t < self.up_at

    def kill(self, k: float) -> None:
        """The orchestrator kills the process at k: what it held is lost, a new one starts."""
        self.alive = False
        self.kill_at, self.up_at = k, k + RESTART
        self.kills.append((round(k, 4), round(k + RESTART, 4)))
        for req in list(self.inflight.values()):
            if req.start < k:
                self.resolve(req, KILLED, k)
            else:
                self.resolve(req, DOWN, req.start)
        for sent, _ in self.hcs:
            self.health.append((sent, max(sent, k), False))
        self.hcs.clear()
        self.rt.reset(k)  # its pools are gone, and until a new one starts nothing it runs takes time
        for task in asyncio.all_tasks(asyncio.get_running_loop()):
            if task.get_context().get(PROC) == self.gen:
                task.cancel()
        self.spawn(self.boot(self.up_at))

    def sweep(self, t: float) -> None:
        """Health checks whose fate is known at t: answered, or 1 s gone by. Three failures in a row kill
        the process (at the moment the third one timed out)."""
        while self.next_hc <= t:  # sent on time: the load balancer is another machine
            sent = self.next_hc
            self.next_hc += HC_EVERY
            if self.is_down(sent) or not self.alive:
                self.health.append((sent, sent, False))  # connection refused
                continue
            hc = [sent, None]
            self.hcs.append(hc)
            self.run_in_process(self.check(hc))
        hcs = self.hcs
        while hcs:
            sent, answered = hcs[0]
            if answered is None and sent + HC_TIMEOUT > t:
                return
            hcs.popleft()
            ok = answered is not None and answered - sent <= HC_TIMEOUT
            end = answered if ok else sent + HC_TIMEOUT
            self.health.append((sent, end, ok))
            self.fails = 0 if ok else self.fails + 1
            if self.fails >= HC_FAILS:
                self.kill(end)
                return

    # ---------------------------------------------------------------- requests

    def resolve(self, req: Req, outcome: int, t: float) -> None:
        req.done = True
        self.inflight.pop(req.id, None)
        if outcome in (OK, SHED) and t - req.start > TIMEOUT:
            outcome = TIMED_OUT  # the user had gone already
        end = req.start + TIMEOUT if outcome == TIMED_OUT else t
        self.requests.append((req.id, req.start, round(end, 5), req.route, outcome == OK, outcome))

    def finish(self, req: Req, outcome: int) -> None:
        t = now()
        self.sweep(t)
        if not req.done:
            self.resolve(req, outcome, t)

    def expire(self, t: float) -> None:
        """Users who gave up: 504 at start + TIMEOUT, whatever the handler still does."""
        for req in list(itertools.takewhile(lambda r: r.start + TIMEOUT <= t, self.inflight.values())):
            self.resolve(req, TIMED_OUT, t)

    async def handle(self, req: Req, service, call: Call | None) -> None:
        try:
            block(PARSE)
            if call is None:
                await asyncio.sleep(self.work_rng.uniform(*ASYNC_DB))
            else:
                try:
                    await service.run_blocking(call)
                except Overloaded:
                    self.finish(req, SHED)
                    return
            block(RENDER)
            self.finish(req, OK)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a bug in the code under test: surface it
            self.bugs.append(exc)

    def incident_at(self, t: float) -> list[Planned]:
        return [i for i in self.planned[-3:] if i.t0 <= t < i.t1]

    def rates(self, t: float) -> list[float]:
        """Requests/s per route at t."""
        base = rate_at(self.rate, t, self.seed)
        out = [base * m for m in MIX]
        for inc in self.incident_at(t):
            if inc.kind == "uploads":
                out[RESIZE] *= UPLOAD_RATE
            elif inc.kind == "reports":
                out[REPORT] *= REPORT_RATE
        return out

    def call_for(self, route: int, t: float) -> Call:
        seconds = SECONDS[route]
        for inc in self.incident_at(t):
            if inc.kind == "uploads" and route == RESIZE:
                seconds = inc.severity / (self.rate * MIX[RESIZE] * UPLOAD_RATE)
            elif inc.kind == "reports" and route == REPORT:
                seconds = inc.severity / (self.rate * MIX[REPORT] * REPORT_RATE)
            elif inc.kind == "slow_dep" and route in (DB, HTTP):
                seconds *= inc.severity
        return Call(ROUTE_NAMES[route], seconds * self.work_rng.uniform(0.5, 1.5), CPU[route])

    def arrive(self, t: float, route: int) -> None:
        rid = next(self.ids)
        req = Req(rid, round(t, 5), route)
        if self.is_down(t) or not self.alive or self.service is None:  # nobody listens: the LB answers 503
            self.requests.append((rid, req.start, req.start, route, False, DOWN))
            return
        self.inflight[rid] = req
        call = None if route == LIGHT else self.call_for(route, t)
        self.run_in_process(self.handle(req, self.service, call))

    async def traffic(self) -> None:
        """Users arrive as a Poisson process (thinned to the drifting rate and the incidents' mix)."""
        rng = random.Random(self.seed * 17)
        peak = self.rate * PEAK
        t = 0.0
        while True:
            t += rng.expovariate(peak)
            rates = self.rates(t)
            u = rng.random() * peak
            if u >= sum(rates):
                continue
            route = 0
            for route, r in enumerate(rates):
                if u < r:
                    break
                u -= r
            if t > now():
                await asyncio.sleep(t - now())
            self.sweep(now())
            self.arrive(t, route)

    async def balancer(self) -> None:
        """The load balancer's health checks, every HC_EVERY s: sweep() sends them and judges them."""
        while True:
            await asyncio.sleep(max(0.0, self.next_hc - now()))
            self.sweep(now())

    async def check(self, hc: list) -> None:
        block(HC_CPU)
        hc[1] = now()
        self.sweep(now())

    async def probe(self) -> None:
        """The loop's lag, measured outside your code: how late a timer runs."""
        while True:
            t = now()
            await asyncio.sleep(PROBE)
            late = now() - t - PROBE
            self.sweep(now())
            if self.alive and self.up_since <= t:
                self.lags.append((round(t + PROBE, 4), round(late, 5)))

    async def collector(self, inc: Planned) -> None:
        """Garbage-collection pauses: the whole process stops, again and again, until the incident ends."""
        rng = random.Random(f"{self.seed}:{inc.t0}:gc")
        while True:
            await asyncio.sleep(rng.uniform(*GC_GAP))
            if now() >= inc.t1:
                return
            if self.alive:
                block(inc.severity * rng.uniform(0.8, 1.2), "gc")

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(max(0.0, inc.t0 - now()))
            if inc.kind == "gc":
                self.spawn(self.collector(inc))
            await asyncio.sleep(max(0.0, inc.t1 - now()))

    async def sampler(self) -> None:
        while True:
            await asyncio.sleep(SAMPLE)
            t = now()
            self.sweep(t)
            self.expire(t)
            pools = self.rt.snapshot() if self.alive else ()
            self.samples.append((round(t, 4), self.alive, sum(p[3] for p in pools), sum(p[2] for p in pools),
                                 pools, len(self.inflight)))

    def start(self) -> None:
        api.install(asyncio.get_running_loop(), self.rt)
        for coro in (self.boot(0.0), self.traffic(), self.balancer(), self.probe(), self.chaos(), self.sampler()):
            self.spawn(coro)

    def loop_rows(self, a: float, b: float) -> list[tuple]:
        out = []
        for s in sorted(k for k in self.secs if k < b):
            row = self.secs.pop(s)
            if s >= a:
                out.append((float(s), *(round(x, 5) for x in row)))
        return out


async def _start(s: _Sim) -> None:
    s.start()


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 100.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    sim.spawn(_start(s))
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            s.expire(sim.now)
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    "requests": _take(s.requests, 1, a, b),
                    "health": _take(s.health, 0, a, b),
                    "lags": _take(s.lags, 0, a, b),
                    "reports": _take(s.reports, 0, a, b),
                    "blocks": _take(s.blocks, 0, a, b),
                    "calls": _take(s.calls, 1, a, b),
                    "samples": _take(s.samples, 0, a, b),
                    "kills": _take(s.kills, 0, a, b),
                    "loop": s.loop_rows(a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 100.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
