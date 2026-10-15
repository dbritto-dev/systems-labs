"""Lab geo_replication: one endless run on virtual time, handed out a minute at a time.

A profile and settings service in three regions, us, eu and ap, one `RegionNode` each, on a
network with real distances (api.py: ~70-150 ms one way between regions, ~1 ms inside one).
600 users, 200 living in each region, read and write their own profile and read other people's
(~`rate` operations a second, 20% writes; after saving, half of them look at it right away).
The global load balancer sends every user to their own region; the user's app retries once, in
the next region, on a timeout or an error.

Incidents come at random, like in production: a whole region goes down (a power failure, a bad
config push, a cloud outage), a region is cut off from the other two (its users still reach it),
the link between two regions gets slow and drops packets (a subsea cable cut), or a region has
its peak (morning there: three times its traffic). The first one is always us, the primary of
stages 0 and 1, cut off from eu and ap at 0:20-0:32 (a fiber cut): its users still reach it.

The checker knows the truth: for every read of a user's own profile it knows the last write that
user got acknowledged; and every 0.2 s it looks inside each region's `store` (outside the network)
to count the acknowledged writes only one region holds.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from array import array
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Delivery, Message, Network, RPCError
from core.vtime import VirtualRun, now
from labs.geo_replication import lab
from labs.geo_replication.api import CAPACITY, FAILOVER, JITTER, MAX_QUEUE, REGIONS, between

LAB = "geo_replication"
NAMES = ("RegionNode",)
PIECE = 60.0
DRAIN = 5.0  # simulate this far past a minute before handing it out
USERS = 200  # per region: users 0-199 live in us, 200-399 in eu, 400-599 in ap
SHARE = (0.36, 0.34, 0.30)  # of the traffic, by the users' region
WRITE_SHARE = 0.2
OWN_READ = 0.7  # of the reads: a user's own profile (the rest: someone else's)
READ_BACK = 0.5  # after saving, half the users look at their profile right away
ATTEMPT = 0.6  # seconds the app waits for a region before it retries in the next one
AVOID = 3.0  # after a region fails a read (or a write), the app tries the next one first for its
#              reads (or writes) for this long, like the Cosmos DB and DynamoDB SDKs
DETECT = 1.0  # the load balancer moves a down region's users this long after it goes down ...
RECOVER = 0.5  # ... and back this long after it recovers (its health checks pass: caught up or not)
TTL = 4.0  # DNS caches expire over this long after a change: meanwhile requests go the old or new way
SAMPLE = 0.2  # how often the checker looks inside the regions
LINK_LOSS = 0.1  # share of messages a slow link drops
SERVICE = 1.0 / CAPACITY
LINKS = (("us", "eu"), ("us", "ap"), ("eu", "ap"))
# Where a user's app goes: their own region, then the next one (the load balancer skips a region it
# knows is down).
ORDER = {r: [r, FAILOVER[r]] + [x for x in REGIONS if x not in (r, FAILOVER[r])] for r in REGIONS}
READ, WRITE = 0, 1

# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 32.0, "partition", 1.0, "fiber_cut")
KINDS = [
    Kind("down", 0.35, median=12.0, shortest=6.0, longest=25.0, causes=("power", "config_push", "cloud_outage", "cooling")),
    Kind("partition", 0.25, median=10.0, shortest=5.0, longest=20.0, causes=("fiber_cut", "bgp_leak", "firewall")),
    Kind("slow", 0.25, median=12.0, shortest=6.0, longest=25.0, severity=(0.15, 0.35),
         causes=("cable_cut", "congestion", "reroute")),
    Kind("peak", 0.15, median=15.0, shortest=8.0, longest=25.0, severity=(2.5, 3.0),
         causes=("morning", "launch", "tv_show")),
]
MEAN_GAP = 25.0
QUIET = 20.0  # calm after an incident: its after-window is judged before the next one


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def victim(inc: Planned, seed: int) -> int:
    """The region an incident hits (0 us, 1 eu, 2 ap), or for a slow link, the link (an index into
    LINKS). The first incident always hits us."""
    if inc.t0 == FIRST.t0:
        return 0
    return random.Random(f"{seed}:{inc.t0}:victim").randrange(3)


def cut_region(kind: str, hit: int) -> int | None:
    """The region whose users cannot be served at home during an incident (down or cut off)."""
    return hit if kind in ("down", "partition") else None


def _value_of(entry):
    """What a region stores for a key, whatever shape it uses: (version, value) or a value."""
    if isinstance(entry, (tuple, list)) and entry:
        return entry[-1]
    return entry


class _Net(Network):
    """The network between the regions: distances, a region down or cut off, a slow link, and each
    region's capacity for reads and writes."""

    def __init__(self, seed: int) -> None:
        super().__init__(latency=0.0, jitter=JITTER, seed=seed)
        self.where: dict[str, int] = {}  # endpoint -> region index
        self.down: set[int] = set()
        self.cut_off: set[int] = set()
        self.slow: tuple[int, int, float] | None = None  # (region, region, extra seconds one way)
        self.free_at = [0.0] * 3
        self.own = [0] * 3  # reads and writes served since the last sample, from the region's own users
        self.other = [0] * 3  # ... from anywhere else (forwarded, or users sent here by a failover)
        self.shed = [0] * 3

    def _blocked(self, msg: Message, a: int, b: int, servers: bool) -> bool:
        """Dropped: to or from a region that is down (users live outside it), or between servers
        when one of them is cut off."""
        if (b in self.down and self.nodes[msg.dest].is_server) or (a in self.down and self.nodes[msg.src].is_server):
            return True
        return servers and a != b and (a in self.cut_off or b in self.cut_off)

    def send(self, src: str, dest: str, body) -> None:
        if dest not in self.nodes:
            raise ValueError(f"{src} sent a message to {dest!r}, which does not exist")
        msg = Message(src, dest, dict(body), next(self._ids))
        a, b = self.where[src], self.where[dest]
        servers = self.nodes[src].is_server and self.nodes[dest].is_server
        rec = None
        if servers and a != b:  # the picture shows messages between regions
            rec = Delivery(now(), src, dest, str(body.get("type", "")))
            self.log.append(rec)
        if self._blocked(msg, a, b, servers):
            if rec is not None:
                rec.dropped = True
            return
        delay = between(REGIONS[a], REGIONS[b]) * (1 + self.jitter * (2 * self.rng.random() - 1))
        if self.slow is not None and {a, b} == set(self.slow[:2]):
            delay += self.slow[2]
            if self.rng.random() < LINK_LOSS:
                if rec is not None:
                    rec.dropped = True
                return
        asyncio.get_running_loop().call_later(delay, self._land, msg, rec, servers)

    def _land(self, msg: Message, rec: Delivery | None, servers: bool) -> None:
        a, b = self.where[msg.src], self.where[msg.dest]
        if self._blocked(msg, a, b, servers):  # it went down, or was cut off, while this was on the wire
            if rec is not None:
                rec.dropped = True
            return
        if rec is not None:
            rec.arrived = now()
        node = self.nodes[msg.dest]
        if node.is_server and msg.body.get("type") in ("read", "write") and "in_reply_to" not in msg.body:
            t = now()
            start = max(t, self.free_at[b])
            if start - t > MAX_QUEUE:  # the region's load balancer sheds it
                self.shed[b] += 1
                return
            self.free_at[b] = start + SERVICE
            if a == b and not self.nodes[msg.src].is_server:
                self.own[b] += 1
            else:
                self.other[b] += 1
            asyncio.get_running_loop().call_later(start + SERVICE - t, self._handle, msg, b)
        else:
            node._deliver(msg)

    def _handle(self, msg: Message, region: int) -> None:
        if region not in self.down:
            self.nodes[msg.dest]._deliver(msg)


class _Tokens:
    """(user, key) -> the session token: the newest version of that profile the user has written or
    read (0 if none). Every user reads everybody's profile, so a long run fills in all 600 x 600;
    as a dict that is ~70 MB, as an array of floats 2.9 MB from the start. A version that is not a
    float (some other code's counter) is kept as it is, in a dict."""

    __slots__ = ("_n", "_floats", "_other")

    def __init__(self, users: int, keys: int) -> None:
        self._n = keys
        self._floats = array("d", [0.0]) * (users * keys)  # 0.0: none
        self._other: dict = {}

    def _at(self, user: int, key: str) -> int | None:
        k = int(key[1:]) if key[:1] == "u" and key[1:].isdigit() else -1
        return user * self._n + k if 0 <= k < self._n and 0 <= user < len(self._floats) // self._n else None

    def get(self, uk: tuple[int, str], default=0):
        i = self._at(*uk)
        if i is None or i in self._other:
            return self._other.get(uk if i is None else i, default)
        return self._floats[i] or default

    def __setitem__(self, uk: tuple[int, str], value) -> None:
        i = self._at(*uk)
        if i is None:
            self._other[uk] = value
        elif type(value) is float and value > 0:
            self._floats[i] = value
            self._other.pop(i, None)
        else:
            self._floats[i] = 0.0
            if type(value) is int and value == 0:
                self._other.pop(i, None)  # 0 is what get answers for none
            else:
                self._other[i] = value


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.code, self.seed, self.rate = code, seed, rate
        self.rng = random.Random(seed * 17 + 3)
        self.net = _Net(seed)
        self.nodes: list = []
        self.clients: list[Client] = []
        for i, r in enumerate(REGIONS):
            c = Client(f"app-{r}")
            self.net.join(c)
            self.net.where[c.node_id] = i
            self.clients.append(c)
        self.dns_down = [False] * 3  # what the load balancer says now
        self.dns_since = [-TTL] * 3  # when it last changed its mind about each region
        self.planned: list[Planned] = []
        self.hits: dict[float, int] = {}
        self.busy: set[int] = set()  # users with a request in flight (an app does one at a time)
        self.avoid: dict[tuple[int, int], dict[int, float]] = {}  # (user, read/write) -> {region: until}
        self.tokens = _Tokens(3 * USERS, 3 * USERS)  # (user, key) -> the session token
        self.acked: dict[int, int] = {}  # user -> the value of their last acknowledged write
        self.newest: dict[str, int] = {}  # key -> its newest acknowledged value
        self.pending: set[str] = set()  # keys whose newest acknowledged value is not yet in 2 regions
        self.lacking: list[set[str]] = [set(), set(), set()]  # per region: keys it lacks the newest of
        self.ops: list[tuple] = []
        self.samples: list[tuple] = []
        self.open: dict[int, float] = {}
        self._ids = itertools.count()
        self._value = itertools.count(1)

    async def setup(self) -> None:
        for i, r in enumerate(REGIONS):
            node = self.code.RegionNode(r, list(REGIONS))
            if not hasattr(node, "store"):
                raise AttributeError(lab_text(LAB).STRINGS["no_store"])
            self.net.join(node)
            self.net.where[r] = i
            self.nodes.append(node)

    # ---- users

    def believed_down(self, region: int) -> bool:
        """Whether this request's DNS answer says the region is down. For TTL seconds after the load
        balancer changes its mind, some apps still have the old answer cached."""
        new = self.dns_down[region]
        age = now() - self.dns_since[region]
        if age < TTL and self.rng.random() >= age / TTL:
            return not new
        return new

    def route(self, user: int, kind: int) -> list[int]:
        """The regions a user's app tries, in order: the load balancer skips the ones it says are down,
        and the app puts last a region that failed one of its reads (or writes) in the last AVOID s."""
        order = [REGIONS.index(r) for r in ORDER[REGIONS[user // USERS]]]
        order = [r for r in order if not self.believed_down(r)] or order
        avoid = self.avoid.get((user, kind))
        if avoid:
            t = now()
            order.sort(key=lambda r: avoid.get(r, 0.0) > t)  # stable: the usual order otherwise
        return order[:2]

    async def op(self, user: int, kind: int, key: str) -> bool:
        home = user // USERS
        own = key == f"u{user}"
        start = now()
        k = next(self._ids)
        self.open[k] = start
        token = self.tokens.get((user, key), 0)
        must = self.acked.get(user) if own and kind == READ else None
        body = {"type": "read" if kind == READ else "write", "key": key, "token": token}
        value = 0
        if kind == WRITE:
            value = body["value"] = next(self._value)
        tried = self.route(user, kind)
        ok, served, reply, attempts = False, -1, {}, 0
        for r in tried:
            attempts += 1
            try:
                reply = await self.clients[home].rpc(REGIONS[r], body, timeout=ATTEMPT)
            except (TimeoutError, RPCError):
                reply = {}
            if reply.get("type") == ("read_ok" if kind == READ else "write_ok"):
                ok, served = True, r
                break
            self.avoid.setdefault((user, kind), {})[r] = now() + AVOID
        stale = False
        if ok:
            version = reply.get("version")
            if isinstance(version, (int, float)) and not isinstance(version, bool):
                self.tokens[(user, key)] = max(token, version)
            if kind == WRITE:
                self.acked[user] = value
                self.newest[key] = value
                self.pending.add(key)
                for lacking in self.lacking:
                    lacking.add(key)
            elif must is not None:
                got = reply.get("value")
                stale = not isinstance(got, int) or got < must
        del self.open[k]
        self.ops.append((start, home, kind, own, tried[0], served, now(), ok, stale, attempts))
        return ok

    async def session(self, user: int, kind: int, key: str) -> None:
        self.busy.add(user)
        try:
            ok = await self.op(user, kind, key)
            if ok and kind == WRITE and self.rng.random() < READ_BACK:  # look at it right away
                await asyncio.sleep(self.rng.uniform(0.02, 0.06))
                await self.op(user, READ, key)
        finally:
            self.busy.discard(user)

    def start_one(self, region: int, rng: random.Random) -> None:
        user = region * USERS + rng.randrange(USERS)
        if user in self.busy:
            return
        if rng.random() < WRITE_SHARE:
            kind, key = WRITE, f"u{user}"
        elif rng.random() < OWN_READ:
            kind, key = READ, f"u{user}"
        else:
            kind, key = READ, f"u{rng.randrange(3 * USERS)}"
        asyncio.ensure_future(self.session(user, kind, key))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 11 + 3)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            self.start_one(rng.choices((0, 1, 2), SHARE)[0], rng)

    async def peak(self, inc: Planned, region: int) -> None:
        """The region's extra traffic during its peak: (severity - 1) times its usual share."""
        rng = random.Random(f"{self.seed}:{inc.t0}:peak")
        extra = self.rate * SHARE[region] * (inc.severity - 1)
        t = inc.t0
        while True:
            t += rng.expovariate(extra)
            if t >= inc.t1:
                return
            await asyncio.sleep(t - now())
            self.start_one(region, rng)

    # ---- incidents

    async def dns(self, region: int, down: bool, at: float) -> None:
        await asyncio.sleep(max(0.0, at - now()))
        self.dns_down[region] = down
        self.dns_since[region] = now()

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            hit = self.hits[inc.t0] = victim(inc, self.seed)
            if inc.kind == "down":
                self.net.down.add(hit)
                asyncio.ensure_future(self.dns(hit, True, inc.t0 + DETECT))
            elif inc.kind == "partition":
                self.net.cut_off.add(hit)
            elif inc.kind == "slow":
                a, b = LINKS[hit]
                self.net.slow = (REGIONS.index(a), REGIONS.index(b), inc.severity)
            else:
                asyncio.ensure_future(self.peak(inc, hit))
            await asyncio.sleep(inc.t1 - now())
            if inc.kind == "down":
                self.net.down.discard(hit)
                asyncio.ensure_future(self.dns(hit, False, inc.t1 + RECOVER))
            self.net.cut_off.discard(hit)
            self.net.slow = None

    # ---- the checker

    def holds(self, region: int, key: str, value: int) -> bool:
        got = _value_of(self.nodes[region].store.get(key))
        return isinstance(got, int) and got >= value

    async def checker(self) -> None:
        """Every SAMPLE: which region lacks which acknowledged write, and how many have one copy only."""
        while True:
            await asyncio.sleep(SAMPLE)
            for r, lacking in enumerate(self.lacking):
                for key in [k for k in lacking if self.holds(r, k, self.newest[k])]:
                    lacking.discard(key)
            risk = 0
            for key in list(self.pending):
                if sum(key not in lacking for lacking in self.lacking) >= 2:
                    self.pending.discard(key)
                else:
                    risk += 1
            net = self.net
            self.samples.append((
                now(), tuple(r not in net.down for r in range(3)), tuple(r in net.cut_off for r in range(3)),
                tuple(self.dns_down), tuple(len(x) for x in self.lacking),
                tuple(round(min(1.0, (o + x) * SERVICE / SAMPLE), 3) for o, x in zip(net.own, net.other)),
                tuple(net.own), tuple(net.other), tuple(net.shed), risk,
            ))
            net.own, net.other, net.shed = [0] * 3, [0] * 3, [0] * 3

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between regions sent in [a, b): (sent, src, dest, arrived or None, a user's request?)."""
        out, keep = [], []
        where = self.net.where
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)
                continue
            if d.sent >= a:
                out.append((d.sent, where[d.src], where[d.dest], d.arrived, d.type in ("read", "write")))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 200.0) -> Iterator[dict]:
    """Pieces of one endless run: minute k holds what started in [60k, 60k + 60)."""
    code = load(LAB, variant, NAMES) if isinstance(variant, str) else variant
    sim = VirtualRun()
    s = _Sim(code, seed, rate)
    for coro in (s.setup(), s.traffic(), s.chaos(), s.checker()):
        sim.spawn(coro)
    try:
        for k in itertools.count():
            a, b = k * PIECE, (k + 1) * PIECE
            sim.run_until(b + DRAIN)
            if s.net.bugs:
                raise s.net.bugs[0]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in s.planned if a <= i.t0 < b],
                "hits": {i.t0: s.hits.get(i.t0, victim(i, seed)) for i in s.planned if a <= i.t0 < b},
                "tables": {
                    # (start, home region, read/write, own profile?, region tried first, region that
                    #  answered or -1, end, answered, missed own write, attempts)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src region, dest region, arrived or None if dropped, a user's request?)
                    "msgs": s.messages(a, b),
                    # (t, up, cut off, load balancer says down, keys behind, busy share, own users'
                    #  requests, other requests, shed, writes with one copy): per region, every 0.2 s
                    "regions": _take(s.samples, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
