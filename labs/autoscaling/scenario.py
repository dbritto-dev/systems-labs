"""Lab autoscaling: one endless run on virtual time, handed out a minute at a time.

Users send requests at a rate that follows a compressed day (a 10-minute "day": quiet at night,
busy at the peak), drifts like real traffic and comes in short bursts. A load balancer spreads
them over a fleet of instances (power of two choices on requests in flight). An instance works on
2 requests at once (~100 ms each, so ~20 requests/s when warm) and queues the rest; a user gives up
after 2 s (a 504), and the instance skips a queued request whose user is gone.

Every TICK seconds the scenario asks your `Autoscaler.desired(metrics)` how many instances the
fleet should have, then launches or terminates instances to get there (between MIN_INSTANCES and
MAX_INSTANCES). A new instance boots for 20-35 s (paid for, not serving), then serves but is
slow while it warms up (cold caches, a cold JIT: 2x slower at first, warm after 20 s). Cost is
instance-seconds: every instance you have, booting or not.

Incidents come at random, like in production: a traffic surge (a TV ad, a marketing push, a viral
post, a flash sale), a sudden drop (a region fails over away, an upstream outage, a broken client
release), noisy CPU (a batch job, a backup or a log shipper on the same hosts: the CPU reading
goes up, the capacity does not) and a cold-start wave (a rolling deploy restarts the instances
batch by batch: each one is cold again). The first incident is always a 2x surge at 0:20-2:00.
The fleet at 0:00 was sized by hand for the morning (65% busy). The run never restarts: the fleet, its queues and the clock carry on from one minute to the next.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import math
import random
from collections import deque
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, rate_at, schedule
from core.vtime import VirtualRun, now

LAB = "autoscaling"
NAMES = ("Autoscaler", "Metrics", "cpu_step", "target_tracking")
PIECE = 60.0
DRAIN = 4.0  # simulate this far past a minute before handing it out (every request ends by then)
SAMPLE = 0.5  # how often the fleet is recorded (and billed)

WORKERS = 2  # requests an instance works on at once; the rest wait in its queue
SERVICE = 0.100  # seconds per request on a warm instance (±50%)
CAP = WORKERS / SERVICE  # requests/s a warm instance can do: 40
TIMEOUT = 2.0  # a user gives up after this long (a 504)
BOOT = (20.0, 35.0)  # seconds a new instance boots: paid for, not serving
WARM = 20.0  # seconds a fresh instance takes to warm up once it serves
COLD = 2.0  # how many times slower a fresh instance is at first
MIN_INSTANCES = 2
MAX_INSTANCES = 40
INITIAL_LOAD = 0.65  # the fleet at 0:00 is this busy: sized by hand for the morning, a little tight
TICK = 10.0  # the autoscaler runs this often
FIRST_TICK = 5.0
WINDOW = 10.0  # its metrics cover the last WINDOW seconds

DAY = 600.0  # a compressed day: 10 minutes from one night to the next
DAY_SWING = 0.4  # ±40% around the mean rate over a day
DAY_PEAK = 60.0  # the busiest moment of the day is at 1:00, the quietest at 6:00
SURGE_RAMP = 60.0  # seconds a surge takes to climb (people tune in, the post spreads)
SURGE_DOWN = 20.0  # seconds the traffic takes to fall back after a surge
DROP_DOWN = 8.0  # seconds the traffic takes to fall in a drop
DROP_BACK = 40.0  # seconds it takes to come back after one (traffic fails back gradually)
BURST_GAP = 12.0  # seconds between short bursts of traffic, on average (crawlers, push notifications, cron jobs)
BURST = (2.0, 6.0)  # how long a burst lasts
BURST_HIGH = (0.1, 0.3)  # how much traffic it adds
BATCH_JOB = 30.0  # a noisy batch job runs in bursts: on for 18 s of every 30
DEPLOY_EVERY = 12.0  # seconds between the batches of a rolling deploy

# Causes are keys; their words are in text/<lang>.py (CAUSES), so a trace is the same in any language.
FIRST = Planned(20.0, 120.0, "surge", 2.0, "tv_ad")
KINDS = [
    Kind("surge", 0.35, median=130.0, shortest=120.0, longest=170.0, severity=(1.5, 1.9), causes=(
        "tv_ad", "marketing_push", "viral_post", "flash_sale")),
    Kind("drop", 0.25, median=80.0, shortest=60.0, longest=120.0, severity=(0.4, 0.6), causes=(
        "region_failover", "upstream_outage", "client_bug")),
    Kind("noisy", 0.2, median=60.0, shortest=45.0, longest=90.0, severity=(0.3, 0.5), causes=(
        "batch_job", "backup", "log_shipper")),
    Kind("cold", 0.2, median=60.0, shortest=50.0, longest=80.0, severity=(0.25, 0.35), causes=(
        "deploy", "config_push", "node_rotation")),
]
MEAN_GAP = 40.0
QUIET = 70.0  # at least this calm after an incident: the after window, the baseline, and time to judge

# Instance states in the samples, per slot.
EMPTY, BOOTING, WARMING, WARM_STATE = range(4)


def _s(key: str, **values) -> str:
    """One of the lab's STRINGS in the language in use (errors your code may see)."""
    return lab_text(LAB).STRINGS[key].format(**values)


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def multiplier(inc: Planned, t: float) -> float:
    """How much an incident multiplies the traffic at t (1 when it does not touch it)."""
    if inc.kind == "surge":
        if t < inc.t0 or t > inc.t1 + SURGE_DOWN:
            return 1.0
        if t <= inc.t1:
            return 1.0 + (inc.severity - 1.0) * min(1.0, (t - inc.t0) / SURGE_RAMP)
        return 1.0 + (inc.severity - 1.0) * (1.0 - (t - inc.t1) / SURGE_DOWN)
    if inc.kind == "drop":
        if t < inc.t0 or t > inc.t1 + DROP_BACK:
            return 1.0
        if t <= inc.t1:
            return 1.0 - (1.0 - inc.severity) * min(1.0, (t - inc.t0) / DROP_DOWN)
        return inc.severity + (1.0 - inc.severity) * (t - inc.t1) / DROP_BACK
    return 1.0


def day(t: float) -> float:
    """The time of day: 1 on average, 1 - DAY_SWING at night, 1 + DAY_SWING at the peak."""
    return 1.0 + DAY_SWING * math.cos(2 * math.pi * (t - DAY_PEAK) / DAY)


def noise_cpu(inc: Planned, t: float) -> float:
    """CPU a noisy batch job adds to every host at t (in bursts), 0 when it is not running."""
    if inc.kind != "noisy" or not inc.t0 <= t < inc.t1:
        return 0.0
    return inc.severity * (1.0 if (t - inc.t0) % BATCH_JOB < 18.0 else 0.15)


class Instance:
    """One instance: WORKERS requests at a time, first come first served, the rest wait in a queue.

    Requests are worked out as they arrive (a FIFO queue lets you): when a worker frees up, and how
    long the request takes at the instance's speed then. A request whose user would have given up
    before a worker frees up is skipped (no work); one that is started but ends too late still costs
    the work, and the user gets a 504.
    """

    __slots__ = ("id", "slot", "launched", "ready", "warm", "free", "ends", "rng")

    def __init__(self, iid: int, slot: int, launched: float, ready: float, rng: random.Random) -> None:
        self.id, self.slot, self.launched, self.ready, self.rng = iid, slot, launched, ready, rng
        self.warm = ready + WARM  # warm (full speed) from then on
        self.free = [0.0] * WORKERS  # when each worker is next free (a heap)
        self.ends: list[float] = []  # when each request it works on is done (a heap)

    def slowness(self, t: float) -> float:
        """How many times slower than warm it is at t: COLD when it starts serving, 1 once warm."""
        if t >= self.warm:
            return 1.0
        return 1.0 + (COLD - 1.0) * min(1.0, (self.warm - t) / WARM)

    def state(self, t: float) -> int:
        return BOOTING if t < self.ready else WARMING if t < self.warm else WARM_STATE

    def handle(self, t: float) -> tuple[float, bool, float]:
        """A request arrives at t: (when it ends for the user, answered in time, seconds of work)."""
        free = self.free
        start = max(t, free[0])
        if start - t >= TIMEOUT:  # the user is gone before a worker frees up: skipped
            return t + TIMEOUT, False, 0.0
        heapq.heappop(free)
        work = SERVICE * self.slowness(start) * self.rng.uniform(0.5, 1.5)
        done = start + work
        heapq.heappush(free, done)
        heapq.heappush(self.ends, done)
        if done > t + TIMEOUT:
            return t + TIMEOUT, False, work
        return done, True, work

    def outstanding(self, t: float) -> int:
        """Requests it is working on or has queued at t."""
        ends = self.ends
        while ends and ends[0] <= t:
            heapq.heappop(ends)
        return len(ends)


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.rng = random.Random(seed * 7 + 1)  # the instances' speed and boot times
        self.pick_rng = random.Random(seed * 7 + 2)  # the load balancer
        self.policy = code.Autoscaler()
        self.fleet: list[Instance] = []
        self.slots: list[Instance | None] = [None] * MAX_INSTANCES
        self.iids = itertools.count()
        self.burst_rng = random.Random(seed * 7 + 3)
        self.bursts: deque[tuple[float, float, float]] = deque([(-1.0, -1.0, 0.0)])  # (start, end, extra)
        self.planned: list[Planned] = []
        initial = max(MIN_INSTANCES, math.ceil(self.demand(0.0, bursts=False) / (CAP * INITIAL_LOAD)))
        for _ in range(initial):  # the fleet at 0:00 was sized by hand this morning, and is warm
            inst = self.launch(-WARM - BOOT[1])
            inst.ready, inst.warm = -WARM, 0.0
        self.serving: list[Instance] = []
        self.serving_until = -math.inf  # the serving list holds until the next instance is ready
        self.ids = itertools.count()
        self.requests: list[tuple] = []  # (id, start, end, answered, slot)
        self.samples: list[tuple] = []  # (t, demand, capacity, instances, booting, warming, states, loads, cpu)
        self.ticks: list[tuple] = []  # (t, before, after, rps, cpu, in_flight, booting, warming)
        self.arrived: dict[int, int] = {}  # requests that arrived per second
        self.work: dict[int, float] = {}  # seconds of work started per second
        self.seats: dict[int, float] = {}  # worker-seconds the serving fleet had per second
        self.inflight: dict[int, list[float]] = {}  # (requests in flight per serving instance) samples per second
        self.extra: dict[int, list[float]] = {}  # CPU a noisy neighbour added, samples per second
        self.cpu = 0.0  # the last CPU reading the autoscaler saw
        self.bugs: list[BaseException] = []

    # ---------------------------------------------------------------- the fleet

    def launch(self, t: float) -> Instance:
        slot = self.slots.index(None)
        inst = Instance(next(self.iids), slot, t, t + self.rng.uniform(*BOOT), self.rng)
        self.slots[slot] = inst
        self.fleet.append(inst)
        self.serving_until = -math.inf
        return inst

    def terminate(self, n: int, t: float) -> None:
        """Remove n instances: the ones still booting first (newest first), then the coldest, then the
        least busy. Requests they already hold still finish (a graceful drain); no new ones arrive."""
        order = sorted(self.fleet, key=lambda i: (i.ready <= t, i.warm <= t, i.outstanding(t), -i.launched))
        for inst in order[:n]:
            self.fleet.remove(inst)
            self.slots[inst.slot] = None
        self.serving_until = -math.inf

    def serving_at(self, t: float) -> list[Instance]:
        if t >= self.serving_until:
            self.serving = [i for i in self.fleet if i.ready <= t]
            self.serving_until = min((i.ready for i in self.fleet if i.ready > t), default=math.inf)
        return self.serving

    def demand(self, t: float, bursts: bool = True) -> float:
        """Requests/s the users send at t: the day, the drift, any surge or drop, and short bursts."""
        rate = rate_at(self.rate, t, self.seed) * day(t)
        for inc in self.planned[-3:]:
            rate *= multiplier(inc, t)
        return rate * (self.burst(t) if bursts else 1.0)

    def burst(self, t: float) -> float:
        """Traffic is bursty second to second: 1 + the burst running at t, if any."""
        bursts = self.bursts
        while bursts[-1][0] <= t + 1.0:  # plan bursts a little ahead
            start = bursts[-1][1] + self.burst_rng.expovariate(1.0 / BURST_GAP)
            bursts.append((start, start + self.burst_rng.uniform(*BURST), self.burst_rng.uniform(*BURST_HIGH)))
        while len(bursts) > 2 and bursts[1][1] < t - 1.0:
            bursts.popleft()
        return 1.0 + sum(h for a, b, h in bursts if a <= t < b)

    def noise(self, t: float) -> float:
        return sum(noise_cpu(inc, t) for inc in self.planned[-3:])

    # ---------------------------------------------------------------- tasks

    def request(self, rid: int, t: float) -> None:
        serving = self.serving_at(t)
        s = int(t)
        self.arrived[s] = self.arrived.get(s, 0) + 1
        if not serving:  # nothing serves yet: a 503 at once
            self.requests.append((rid, t, t, False, -1))
            return
        if len(serving) == 1:
            inst = serving[0]
        else:  # power of two choices on requests in flight
            a, b = self.pick_rng.sample(serving, 2)
            inst = a if a.outstanding(t) <= b.outstanding(t) else b
        end, ok, work = inst.handle(t)
        self.work[s] = self.work.get(s, 0.0) + work
        self.requests.append((rid, t, end, ok, inst.slot))

    async def traffic(self) -> None:
        """Users arrive as a Poisson process whose rate follows the day (by thinning)."""
        rng = random.Random(self.seed * 7)
        t = 0.0
        while True:
            peak = self.demand(t, bursts=False) * (1.1 + BURST_HIGH[1]) + 1.0  # a bound for the next moments
            t += rng.expovariate(peak)
            if rng.random() * peak > self.demand(t):
                continue
            await asyncio.sleep(t - now())
            try:
                self.request(next(self.ids), now())
            except Exception as exc:  # a bug in the scenario must not hang the run
                self.bugs.append(exc)
                return

    def metrics(self, t: float):
        """What the autoscaler sees: the last WINDOW seconds, from the load balancer and the hosts."""
        secs = range(max(0, int(t - WINDOW)), int(t))
        rps = sum(self.arrived.get(s, 0) for s in secs) / max(1, len(secs))
        seats = sum(self.seats.get(s, 0.0) for s in secs)
        work = sum(self.work.get(s, 0.0) for s in secs)
        extra = [x for s in secs for x in self.extra.get(s, ())]
        inflight = [x for s in secs for x in self.inflight.get(s, ())]
        cpu = (work / seats if seats else 0.0) + (sum(extra) / len(extra) if extra else 0.0)
        self.cpu = round(min(1.0, cpu), 3)
        booting = sum(i.ready > t for i in self.fleet)
        warming = sum(i.ready <= t < i.warm for i in self.fleet)
        return self.code.Metrics(t=t, instances=len(self.fleet), booting=booting, warming=warming,
                                 rps=round(rps, 1), cpu=self.cpu,
                                 in_flight=round(sum(inflight) / len(inflight), 2) if inflight else 0.0)

    async def autoscaler(self) -> None:
        await asyncio.sleep(FIRST_TICK)
        while True:
            t = now()
            m = self.metrics(t)
            try:
                want = self.policy.desired(m)
            except Exception as exc:  # a bug in the code under test: surface it
                self.bugs.append(exc)
                return
            if isinstance(want, bool) or not isinstance(want, int):
                self.bugs.append(TypeError(_s("bad_desired", value=repr(want))))
                return
            before = len(self.fleet)
            after = max(MIN_INSTANCES, min(MAX_INSTANCES, want))
            if after > before:
                for _ in range(after - before):
                    self.launch(t)
            elif after < before:
                self.terminate(before - after, t)
            self.ticks.append((round(t, 3), before, after, m.rps, m.cpu, m.in_flight, m.booting, m.warming))
            await asyncio.sleep(TICK)

    async def deploy(self, inc: Planned) -> None:
        """A rolling deploy: every DEPLOY_EVERY s, restart a batch of the instances not yet restarted.
        A restarted instance is back in seconds, but cold: slow until it warms up again."""
        done: set[int] = set()
        while now() < inc.t1 - WARM:
            t = now()
            left = [i for i in self.fleet if i.id not in done and i.ready <= t]
            if not left:
                break
            batch = max(1, math.ceil(inc.severity * len(self.fleet)))
            for inst in left[:batch]:
                done.add(inst.id)
                inst.warm = t + WARM
            await asyncio.sleep(DEPLOY_EVERY)

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            if inc.kind == "cold":
                asyncio.get_running_loop().create_task(self.deploy(inc))
            await asyncio.sleep(max(0.0, inc.t1 - now()))
            await asyncio.sleep(max(0.0, inc.t1 + DROP_BACK - now()))  # let the traffic settle first

    async def sampler(self) -> None:
        while True:
            t = now()
            serving = self.serving_at(t)
            s = int(t)
            self.seats[s] = self.seats.get(s, 0.0) + len(serving) * WORKERS * SAMPLE
            loads = [0] * MAX_INSTANCES
            states = [EMPTY] * MAX_INSTANCES
            for inst in self.fleet:
                loads[inst.slot] = inst.outstanding(t)
                states[inst.slot] = inst.state(t)
            if serving:
                self.inflight.setdefault(s, []).append(sum(loads) / len(serving))
            self.extra.setdefault(s, []).append(self.noise(t))
            capacity = sum(CAP / i.slowness(t) for i in serving)
            booting = sum(st == BOOTING for st in states)
            warming = sum(st == WARMING for st in states)
            self.samples.append((round(t, 3), round(self.demand(t), 1), round(capacity, 1), len(self.fleet),
                                 booting, warming, tuple(states), tuple(loads), self.cpu))
            for old in [k for k in self.arrived if k < s - 2 * WINDOW]:
                for d in (self.arrived, self.work, self.seats, self.inflight, self.extra):
                    d.pop(old, None)
            await asyncio.sleep(SAMPLE)

    @staticmethod
    def take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
        """Remove rows whose time `col` is before b; return those in [a, b), sorted."""
        out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
        rows[:] = [r for r in rows if r[col] >= b]
        return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 120.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for task in (s.traffic(), s.chaos(), s.sampler(), s.autoscaler()):
        sim.spawn(task)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.bugs:
                raise s.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "tables": {
                    "requests": s.take(s.requests, 1, a, b),
                    "samples": s.take(s.samples, 0, a, b),
                    "ticks": s.take(s.ticks, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, rate: float = 120.0) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, rate), chunk, None))
