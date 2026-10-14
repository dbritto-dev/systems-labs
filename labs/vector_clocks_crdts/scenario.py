"""Lab vector_clocks_crdts: multi-leader shopping carts, one endless run on virtual time.

5 replicas on a simulated network (~100 ms per message), each in its own site. Every replica
takes writes locally (multi-leader, offline-first) and gossips its carts to the others. A cart
is shared by two devices (a phone and a laptop, two people in a household), each near a
different replica; each device adds and removes its own products (6 of the cart's 12) and
reads the whole cart. Clients always reach their replica: only the links between replicas fail.

Incidents, like in production: the network splits the replicas in two (both sides keep taking
writes), one replica goes offline from the others (its site keeps serving, and it comes back
with old state plus its own edits), or one replica's wall clock jumps (an NTP step), so its
timestamps lie. The first incident always splits {n0, n1} from {n2, n3, n4} at 0:20-0:30.

The checker looks inside the replicas (`items(cart)`), outside the network. An acknowledged add
is *lost* when its product is missing from the replica that took it while it should be there;
an acknowledged remove is *back* (resurrected) when the product shows up there again.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections import Counter
from collections.abc import Iterator

from core.contract import load
from core.i18n import lab_text
from core.incidents import Kind, Planned, arrivals, schedule
from core.net import Client, Network
from core.vtime import VirtualRun, now

LAB = "vector_clocks_crdts"
NAMES = ("CartNode",)
PIECE = 60.0
DRAIN = 5.0
NODES = 5
CARTS = 40
PRODUCTS = 12  # per cart: device 0 handles the even ones, device 1 the odd ones
READS = 0.3  # share of client operations that read the cart
CLIENT_TIMEOUT = 1.0
CHECK_EVERY = 0.25  # how often the checker looks at the replicas
SETTLED = 1.0  # a cart written this recently is still spreading: not judged for convergence
FIRST_GROUPS = [[0, 1], [2, 3, 4]]
# Causes are keys; their words are in text/<lang>.py (CAUSES).
FIRST = Planned(20.0, 30.0, "partition", 1.0, "tor_switch")
KINDS = [
    Kind("partition", 0.4, median=10.0, shortest=5.0, longest=25.0, causes=(
        "tor_switch", "zone_link", "bgp_flap")),
    Kind("offline", 0.35, median=12.0, shortest=6.0, longest=30.0, causes=(
        "fiber_cut", "vpn_cert", "isp_outage")),
    Kind("skew", 0.25, median=10.0, shortest=6.0, longest=20.0, severity=(10.0, 30.0), causes=(
        "ntp_step", "vm_migration", "bad_ntp_server")),
]
MEAN_GAP = 30.0
QUIET = 30.0  # calm after an incident: 10 s to judge it, 15 s of baseline before the next

# Operation kinds, and what the checker finds.
ADD, REMOVE, READ = 0, 1, 2
FINE, LOST, BACK = 0, 1, 2


def incidents(seed: int) -> Iterator[Planned]:
    return schedule(seed, FIRST, KINDS, MEAN_GAP, QUIET)


def groups_for(inc: Planned, seed: int) -> list[list[int]] | None:
    """Which replicas can still talk to each other during the incident (None: no partition)."""
    if inc.kind == "skew":
        return None
    if inc.t0 == FIRST.t0:
        return [list(g) for g in FIRST_GROUPS]
    rng = random.Random(f"{seed}:{inc.t0}:groups")
    small = sorted(rng.sample(range(NODES), 1 if inc.kind == "offline" else 2))
    return [small, [n for n in range(NODES) if n not in small]]


def skew_for(inc: Planned, seed: int) -> tuple[int, float] | None:
    """(replica, seconds its clock is off) for a clock-skew incident: ahead or behind."""
    if inc.kind != "skew":
        return None
    rng = random.Random(f"{seed}:{inc.t0}:skew")
    return rng.randrange(NODES), inc.severity * rng.choice((-1, 1))


def home(cart: int, device: int) -> int:
    """The replica a cart's device talks to: two different replicas per cart."""
    first = cart % NODES
    return first if device == 0 else (first + 1 + (cart // NODES) % (NODES - 1)) % NODES


def cart_name(cart: int) -> str:
    return f"cart{cart}"


def item_name(product: int) -> str:
    return f"p{product}"


class _Sim:
    def __init__(self, code, seed: int, rate: float) -> None:
        self.seed, self.rate = seed, rate
        self.net = Network(latency=0.1, jitter=0.2, seed=seed)
        self.ids = [f"n{i}" for i in range(NODES)]
        self.index = {n: i for i, n in enumerate(self.ids)}
        self.code = code
        self.nodes: list = []
        self.client = Client("c1")
        self.net.join(self.client)
        self.planned: list[Planned] = []
        self.ops: list[tuple] = []  # (start, kind, node, cart, product, end, ok, verdict)
        self.last: dict[tuple[int, int], list] = {}  # (cart, product) -> [kind or None, flagged]
        self.busy: set[tuple[int, int]] = set()  # (cart, product) with a write in flight
        self.busy_carts: Counter = Counter()
        self.wrote: dict[int, float] = {}  # cart -> when a write to it last started or ended
        self.found: list[tuple] = []  # (time, LOST or BACK, node, cart, product)
        self.conv: list[tuple] = []  # (time, converged share, carts diverged per replica)

    async def setup(self) -> None:
        for n in self.ids:
            node = self.code.CartNode(n, self.ids)
            if not callable(getattr(node, "items", None)):
                raise AttributeError(lab_text(LAB).STRINGS["no_items"])
            node.skew = 0.0
            self.net.join(node)
            self.nodes.append(node)

    def _items(self, node: int, cart: int) -> set:
        got = self.nodes[node].items(cart_name(cart))
        return set(got) if got else set()

    async def _write(self, kind: int, node: int, cart: int, product: int) -> None:
        start = now()
        key = (cart, product)
        self.busy.add(key)
        self.busy_carts[cart] += 1
        self.wrote[cart] = start
        body = {"type": "add" if kind == ADD else "remove", "cart": cart_name(cart), "item": item_name(product)}
        try:
            await self.client.rpc(self.ids[node], body, timeout=CLIENT_TIMEOUT)
            ok = True
        except Exception:  # noqa: BLE001 - a timeout or an error reply: the client gives up
            ok = False
        end = now()
        self.busy.discard(key)
        self.busy_carts[cart] -= 1
        self.wrote[cart] = end
        self.last[key] = [kind if ok else None, False]  # a failed write: we do not know what it did
        self.ops.append((start, kind, node, cart, product, end, ok, FINE))

    async def _read(self, node: int, cart: int, device: int) -> None:
        start = now()
        mine = range(device, PRODUCTS, 2)
        expect = {p: self.last[(cart, p)] for p in mine
                  if (cart, p) not in self.busy and self.last.get((cart, p), [None])[0] is not None}
        try:
            reply = await self.client.rpc(self.ids[node], {"type": "read", "cart": cart_name(cart)},
                                          timeout=CLIENT_TIMEOUT)
            items, ok = set(reply.get("items") or ()), True
        except Exception:  # noqa: BLE001
            items, ok = set(), False
        verdict = FINE
        if ok:
            for p, entry in expect.items():
                if self.last.get((cart, p)) is not entry or (cart, p) in self.busy:
                    continue  # the device changed it meanwhile
                present = item_name(p) in items
                if entry[0] == ADD and not present:
                    verdict = LOST
                    break
                if entry[0] == REMOVE and present:
                    verdict = BACK
        self.ops.append((start, READ, node, cart, -1, now(), ok, verdict))

    async def traffic(self) -> None:
        rng = random.Random(self.seed * 13 + 5)
        for t in arrivals(self.rate, self.seed, 0.5, rng):
            await asyncio.sleep(t - now())
            cart, device = rng.randrange(CARTS), rng.randrange(2)
            node = home(cart, device)
            if rng.random() < READS:
                asyncio.ensure_future(self._read(node, cart, device))
                continue
            free = [p for p in range(device, PRODUCTS, 2) if (cart, p) not in self.busy]
            if not free:
                continue
            product = rng.choice(free)
            # Toggle it: remove what the device has in the cart, add (back) what it has not.
            kind = REMOVE if self.last.get((cart, product), [None])[0] == ADD else ADD
            asyncio.ensure_future(self._write(kind, node, cart, product))

    async def chaos(self) -> None:
        for inc in incidents(self.seed):
            self.planned.append(inc)
            await asyncio.sleep(inc.t0 - now())
            groups = groups_for(inc, self.seed)
            skew = skew_for(inc, self.seed)
            if groups is not None:
                self.net.partition([{self.ids[i] for i in g} for g in groups])
            if skew is not None:
                self.nodes[skew[0]].skew = skew[1]
            await asyncio.sleep(inc.t1 - now())
            self.net.heal()
            if skew is not None:
                self.nodes[skew[0]].skew = 0.0  # NTP puts it right again

    async def checker(self) -> None:
        """Every 250 ms: lost adds, resurrected removes, and do the replicas agree? (No traffic.)"""
        while True:
            await asyncio.sleep(CHECK_EVERY)
            t = now()
            seen: dict[tuple[int, int], set] = {}

            def items(node: int, cart: int) -> set:
                got = seen.get((node, cart))
                if got is None:
                    got = seen[(node, cart)] = self._items(node, cart)
                return got

            for (cart, product), entry in self.last.items():
                kind, flagged = entry
                if kind is None or flagged or (cart, product) in self.busy:
                    continue
                node = home(cart, product % 2)
                present = item_name(product) in items(node, cart)
                if kind == ADD and not present:
                    self.found.append((t, LOST, node, cart, product))
                    entry[1] = True
                elif kind == REMOVE and present:
                    self.found.append((t, BACK, node, cart, product))
                    entry[1] = True
            behind = [0] * NODES
            total = agree = 0
            for cart in range(CARTS):
                if self.busy_carts[cart] or t - self.wrote.get(cart, -1e9) < SETTLED:
                    continue
                values = [frozenset(items(n, cart)) for n in range(NODES)]
                total += 1
                common = Counter(values).most_common(1)[0][0]
                if all(v == common for v in values):
                    agree += 1
                else:
                    for n, v in enumerate(values):
                        if v != common:
                            behind[n] += 1
            self.conv.append((t, agree / total if total else 1.0, tuple(behind)))

    def messages(self, a: float, b: float) -> list[tuple]:
        """Messages between replicas sent in [a, b): (sent, src, dest, arrived or None)."""
        out, keep = [], []
        for d in self.net.log:
            if d.sent >= b or (d.arrived is None and not d.dropped):
                keep.append(d)  # later, or still on the wire
                continue
            if d.src in self.index and d.dest in self.index and d.sent >= a:
                out.append((d.sent, self.index[d.src], self.index[d.dest], d.arrived))
        self.net.log[:] = keep
        return out


def _take(rows: list[tuple], col: int, a: float, b: float) -> list[tuple]:
    out = sorted((r for r in rows if r[col] < b), key=lambda r: r[col])
    rows[:] = [r for r in rows if r[col] >= b]
    return [r for r in out if r[col] >= a]


def stream(variant="main", seed: int = 1, rate: float = 20.0) -> Iterator[dict]:
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
            new = [i for i in s.planned if a <= i.t0 < b]
            yield {
                "lab": LAB,
                "start": a,
                "end": b,
                "incidents": [(i.t0, i.t1, i.kind, i.severity, i.cause) for i in new],
                "groups": {i.t0: groups_for(i, seed) for i in new if groups_for(i, seed) is not None},
                "skews": {i.t0: skew_for(i, seed) for i in new if skew_for(i, seed) is not None},
                "tables": {
                    # (start, kind, node, cart, product or -1, end, ok, verdict of a read)
                    "ops": _take(s.ops, 0, a, b),
                    # (sent, src, dest, arrived or None if dropped)
                    "msgs": s.messages(a, b),
                    # (time, converged share, carts diverged per replica)
                    "conv": _take(s.conv, 0, a, b),
                    # (time, LOST or BACK, node, cart, product)
                    "found": _take(s.found, 0, a, b),
                },
            }
    finally:
        sim.close()


def run(variant="main", chunk: int = 0, seed: int = 1, **params) -> dict:
    """Minute `chunk` of the run (simulates every minute before it)."""
    return next(itertools.islice(stream(variant, seed, **params), chunk, None))
