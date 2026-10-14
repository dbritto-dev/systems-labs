import asyncio
import functools
import itertools
import sys

from core.contract import load
from core.net import Client, Network, RPCError
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.distributed_lock import main as given
from labs.distributed_lock import reference as ref
from labs.distributed_lock import scenario

code = load("distributed_lock", variant(), scenario.NAMES)
user = sys.modules[code.Worker.__module__]  # the whole file: its LEASE, its compute


# ------------------------------------------------------------- one solution per stage, as people write them


class Lease(ref.LockService):  # stage 1: leases, but no tokens yet
    async def on_acquire(self, msg):
        job = msg.body["job"]
        if not self.free() and self.holder != job:
            self.reply(msg, {"type": "error", "code": 11})
            return
        self.holder, self.expires = job, self.now() + ref.LEASE
        self.reply(msg, {"type": "acquire_ok"})


class LeaseWorker(ref.Worker):  # renews, but has no token to send (0)
    acquire = given.Worker.acquire


class TrustingStorage(ref.Storage):  # accepts every write
    def is_stale(self, token):
        return False


class NoRenew(LeaseWorker):  # a lease, never renewed: jobs are short, so it still works
    async def renew(self, job):
        return


class LocalCheck(LeaseWorker):  # checks its own clock before each write: the pause comes after the check
    async def acquire(self, job):
        token = await super().acquire(job)
        self.granted = self.now()
        return token

    async def on_job(self, msg):
        job = msg.body["job"]
        if await self.acquire(job) is None:
            self.reply(msg, {"type": "error", "code": 11})
            return
        renewing = self.spawn(self.renew(job))
        try:
            for part in range(ref.PARTS):
                data = await ref.compute(job, part)
                if self.now() - self.granted > ref.LEASE * 0.8:
                    raise TimeoutError("my lease may be gone")
                await self.rpc(ref.STORAGE, {"type": "write", "job": job, "part": part, "data": data},
                               timeout=ref.WRITE_TIMEOUT)
            self.reply(msg, {"type": "job_ok"})
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11})
        finally:
            renewing.cancel()
            self.send(ref.LOCK, {"type": "release", "job": job})


class TokensNoExpiry(ref.LockService):  # fencing tokens on a lock that never expires
    def free(self):
        return self.holder is None


def module(lock=ref.LockService, worker=ref.Worker, storage=ref.Storage, name="Variant"):
    return type(name, (), {"LockService": lock, "Worker": worker, "Storage": storage})


LEASES = module(Lease, LeaseWorker, TrustingStorage, "Leases")
NO_RENEW = module(Lease, NoRenew, TrustingStorage, "NoRenew")
LOCAL_CHECK = module(Lease, LocalCheck, TrustingStorage, "LocalCheck")
UNCHECKED = module(storage=TrustingStorage, name="Unchecked")  # tokens handed out and sent, never checked
NO_EXPIRY = module(lock=TokensNoExpiry, name="NoExpiry")
CORRUPT, STUCK, DONE = range(3)


@functools.cache
def world_of(v, minutes=1, seed=1):
    return build_world("distributed_lock", v, minutes, seed=seed)


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_a_plain_lock_stalls_every_job_while_its_holder_is_frozen():
    for seed in (1, 2, 3):
        world = world_of("main", 1, seed)
        (kind, first), = results(world, "main")
        assert kind == "pause" and first[CORRUPT] and not first[STUCK]
        assert world.stage_index("main") == 0


def test_a_crashed_holder_blocks_a_plain_lock_forever():
    world = build_world("distributed_lock", "main", 4, seed=1)
    crash = [i for i in world.runs["main"].incidents if i.kind in ("crash", "partition")]
    assert crash
    after = [r for r in world.runs["main"].tables["jobs"] if r[0] > crash[0].t1 + 5]
    assert after and not any(r[4] for r in after)  # no job ever finishes again


def test_stage_variants_land_on_their_stage():
    # 0 plain lock (or tokens on a lock that never expires), 1 leases, 2 leases + fencing
    for v, stage in ((NO_EXPIRY, 0), (LEASES, 1), (NO_RENEW, 1), (LOCAL_CHECK, 1), (UNCHECKED, 1),
                     (module(name="Reference"), 2)):
        for seed in (1, 2, 3):
            world = world_of(v, 1, seed)
            assert world.stage_index(v) == stage, (v.__name__, seed, results(world, v))


def test_each_goal_catches_its_mistake():
    (_, leases), = results(world_of(LEASES), LEASES)
    assert not leases[CORRUPT] and leases[STUCK] and leases[DONE]  # the frozen holder's late write
    (_, plain), = results(world_of(NO_EXPIRY), NO_EXPIRY)
    assert plain[CORRUPT] and not plain[STUCK]


def test_leases_corrupt_after_every_pause_and_late_write():
    world = build_world("distributed_lock", LEASES, 5, seed=3)
    res = results(world, LEASES)
    unsafe = [r for kind, r in res if kind in ("pause", "delay")]
    assert len(unsafe) >= 3 and all(not r[CORRUPT] and r[STUCK] for r in unsafe)


def test_reference_passes_every_goal():
    for seed in (1, 3, 4):
        world = build_world("distributed_lock", "reference", 6, seed=seed)
        res = results(world, "reference")
        assert len(res) >= 4 and all(all(r) for _, r in res), (seed, res)
        assert world.stage_index("reference") == 2
    kinds = {i.kind for s in (1, 3, 4) for i in build_world("distributed_lock", "reference", 6, seed=s)
             .runs["reference"].incidents}
    assert kinds == {"pause", "crash", "delay", "partition"}


def test_incidents_are_random_but_the_first_is_a_pause_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "pause") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"pause", "crash", "delay", "partition"} and all(i.cause for i in later)
    for seed in (1, 2, 3):  # it strikes at the first write after 0:20, for 10 s
        first = world_of("reference", 1, seed).runs["reference"].incidents[0]
        assert 20.0 <= first.t0 < 22.0 and abs(first.t1 - first.t0 - 10.0) < 0.05


def test_pieces_join():
    pieces = list(itertools.islice(scenario.stream("reference"), 2))
    starts = [r[0] for p in pieces for r in p["tables"]["jobs"]]
    assert starts == sorted(starts) and starts[-1] < 120
    ids = [r[1] for p in pieces for r in p["tables"]["jobs"]]
    assert len(set(ids)) == len(ids)


# ------------------------------------------------------------- your code


class _Counting(Network):
    def __init__(self) -> None:
        super().__init__(latency=0.01, jitter=0.0)
        self.types: list[str] = []

    def send(self, src, dest, body):
        self.types.append(body.get("type", ""))
        super().send(src, dest, body)


def _cluster(module, *bodies):
    """Run `bodies(nodes, client)` against a lock service, a worker and a storage from `module`."""

    async def main():
        net = _Counting()
        ids = ["lock", "w1", "storage"]
        nodes = {"lock": module.LockService("lock", ids), "w1": module.Worker("w1", ids),
                 "storage": module.Storage("storage", ids)}
        for n in nodes.values():
            net.join(n)
        client = Client("c1")
        net.join(client)
        return [await body(nodes, client) for body in bodies]

    return run_virtual(main())


@your_code(1, "LockService gives the lock back once a lease of LEASE seconds runs out")
def test_stage1_the_lease_expires():
    async def body(nodes, client):
        first = await client.rpc("lock", {"type": "acquire", "job": 1}, timeout=1)
        try:
            await client.rpc("lock", {"type": "acquire", "job": 2}, timeout=1)
            taken = False
        except RPCError:
            taken = True
        await asyncio.sleep(user.LEASE + 0.1)  # job 1 never renews: its lease runs out
        second = await client.rpc("lock", {"type": "acquire", "job": 2}, timeout=1)
        return first["type"], taken, second["type"]

    assert _cluster(code, body) == [("acquire_ok", True, "acquire_ok")]


@your_code(1, "LockService.on_renew keeps the holder's lease; a lost lease cannot be renewed")
def test_stage1_renew():
    async def body(nodes, client):
        await client.rpc("lock", {"type": "acquire", "job": 1}, timeout=1)
        for _ in range(4):  # renewed for twice the lease
            await asyncio.sleep(user.LEASE / 2)
            await client.rpc("lock", {"type": "renew", "job": 1}, timeout=1)
        try:
            await client.rpc("lock", {"type": "acquire", "job": 2}, timeout=1)
            stolen = True
        except RPCError:
            stolen = False
        await asyncio.sleep(user.LEASE + 0.1)
        try:
            await client.rpc("lock", {"type": "renew", "job": 1}, timeout=1)
            late = True
        except RPCError:
            late = False
        return stolen, late

    assert _cluster(code, body) == [(False, False)]


@your_code(1, "Worker renews its lease while a job runs longer than LEASE")
def test_stage1_worker_renews():
    async def slow_compute(job, part):
        await asyncio.sleep(user.LEASE)  # every part takes a whole lease
        return "x"

    async def body(nodes, client):
        reply = asyncio.ensure_future(client.rpc("w1", {"type": "job", "job": 1}, timeout=30))
        await asyncio.sleep(user.LEASE * 1.5)
        try:  # the job still runs, past its first lease: the lock must still be its
            await client.rpc("lock", {"type": "acquire", "job": 2}, timeout=1)
            stolen = True
        except RPCError:
            stolen = False
        return stolen, (await reply)["type"], nodes["w1"].net.types.count("renew") >= 2

    original, user.compute = user.compute, slow_compute
    try:
        assert _cluster(code, body) == [(False, "job_ok", True)]
    finally:
        user.compute = original


@your_code(2, "LockService hands out a token that grows with every grant; Storage refuses older ones")
def test_stage2_fencing_tokens():
    async def body(nodes, client):
        a = (await client.rpc("lock", {"type": "acquire", "job": 1}, timeout=1))["token"]
        await asyncio.sleep(user.LEASE + 0.1)
        b = (await client.rpc("lock", {"type": "acquire", "job": 2}, timeout=1))["token"]
        write = {"type": "write", "part": 0, "data": "x"}
        new = await client.rpc("storage", {**write, "job": 2, "token": b}, timeout=1)
        again = await client.rpc("storage", {**write, "job": 2, "part": 1, "token": b}, timeout=1)
        try:
            await client.rpc("storage", {**write, "job": 1, "token": a}, timeout=1)
            late = "accepted"
        except RPCError as e:
            late = e.code
        return b > a, new["type"], again["type"], late

    assert _cluster(code, body) == [(True, "write_ok", "write_ok", 22)]


@your_code(2, "the frozen holder's late write is refused: no corrupt write, no stall, jobs done")
def test_stage2_first_pause():
    assert [r.ok for r in world_of(variant()).runs[variant()].settled[0]] == [True] * 3


def test_both_pictures():
    from live.canvas import RED
    from live.views import adapter_for, set_view, views_for

    world = build_world("distributed_lock", LEASES, 1)
    assert views_for(world) == ["cluster", "lanes"] and world.view == "cluster"
    first = world.runs[LEASES].incidents[0]
    late = [w for w in world.runs[LEASES].tables["writes"] if w[4] and w[5]]  # accepted, stale
    assert late and first.t1 <= late[0][3] < first.t1 + 1
    t = late[0][3] + 0.1
    frame = adapter_for(world).frame(LEASES, t)
    assert len(frame.nodes) == 6 and RED in [c for *_, c in frame.flights] and frame.nodes[scenario.STORAGE] == RED
    set_view(world, "lanes")
    lanes = adapter_for(world).frame(LEASES, t, 60)
    assert lanes.state[1] == RED and len(lanes.state[0]) <= 13 and RED in [c for c, _ in lanes.outcomes]


def test_main_and_reference_share_the_numbers():
    assert given.LEASE == ref.LEASE and given.PARTS == ref.PARTS
