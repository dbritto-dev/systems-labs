import itertools

from core.contract import load
from core.net import Node
from core.testing import build_world, starting_code, variant, your_code
from labs.transactions import scenario

code = load("transactions", variant(), scenario.NAMES)


# ------------------------------------------------------------- one node per stage, as people write them


class Single(Node):
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.store = {}

    def run(self, msg):
        result, writes = [], []
        for op, key, value in msg.body["txn"]:
            if op == "r":
                result.append(["r", key, self.store.get(key)])
            else:
                self.store[key] = value
                writes.append([key, value])
                result.append(["w", key, value])
        self.reply(msg, {"type": "txn_ok", "txn": result})
        return writes

    async def on_txn(self, msg):
        self.run(msg)


class FireAndForget(Single):  # stage 1: send each write to the others, no retries
    async def on_txn(self, msg):
        for key, value in self.run(msg):
            for n in self.node_ids:
                if n != self.node_id:
                    self.send(n, {"type": "put", "key": key, "value": value})

    async def on_put(self, msg):
        self.store[msg.body["key"]] = msg.body["value"]


class PerWrite(Single):  # stage 2: each write re-sent until acked, newest stamp wins
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.stamps, self.rank, self.counter = {}, node_ids.index(node_id), itertools.count()

    async def on_txn(self, msg):
        stamp = (self.now(), self.rank, next(self.counter))
        for key, value in self.run(msg):
            self.stamps[key] = stamp
            for n in self.node_ids:
                if n != self.node_id:
                    self.spawn(self.push(n, key, value, stamp))

    async def push(self, n, key, value, stamp):
        while True:
            try:
                await self.rpc(n, {"type": "put", "key": key, "value": value, "stamp": list(stamp)}, timeout=0.5)
                return
            except TimeoutError:
                await self.sleep(0.2)

    async def on_put(self, msg):
        key, stamp = msg.body["key"], tuple(msg.body["stamp"])
        if stamp >= self.stamps.get(key, ()):
            self.store[key], self.stamps[key] = msg.body["value"], stamp
        self.reply(msg, {"type": "put_ok"})


def module(cls):
    return type(cls.__name__, (), {"TxnNode": cls})


SINGLE, FIRE, PER_WRITE = module(Single), module(FireAndForget), module(PerWrite)


def results(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_a_single_node_per_store_never_catches_up():
    world = build_world("transactions", SINGLE, 2)
    res = results(world, SINGLE)
    assert res and all(not r[0] for r in res)
    assert world.stage_index(SINGLE) == 0  # Single node


def test_stage_variants_land_on_their_stage_on_every_partition():
    for v, stage, expected in ((FIRE, 1, [True, True, False]),  # Replicated
                               (PER_WRITE, 2, [True, True, True, True, False])):  # Read uncommitted: no G0
        world = build_world("transactions", v, 3)
        res = results(world, v)
        assert len(res) >= 3, res
        assert all(r[:len(expected)] == expected for r in res), (v.__name__, res)
        assert world.stage_index(v) == stage


class AbortButKeep(Single):  # aborts every fifth transaction (error 30), but leaves its writes in the store
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.seen = itertools.count()

    async def on_txn(self, msg):
        if next(self.seen) % 5 == 0:
            for op, key, value in msg.body["txn"]:
                if op == "w":
                    self.store[key] = value
            self.reply(msg, {"type": "error", "code": 30, "text": "txn-conflict"})
        else:
            self.run(msg)


class WritesFirst(Single):  # applies a transaction's writes, waits, then reads: transactions see each other
    async def on_txn(self, msg):
        ops = msg.body["txn"]
        for op, key, value in ops:
            if op == "w":
                self.store[key] = value
        await self.sleep(0.05)
        self.reply(msg, {"type": "txn_ok", "txn": [[op, key, self.store.get(key) if op == "r" else value]
                                                   for op, key, value in ops]})


def test_the_checker_catches_what_6b_and_6c_forbid():
    """Fly.io 6b (read uncommitted) forbids G0; 6c (read committed) also G1a, G1b and G1c. Each is caught:
    per-key messages that arrive in different orders (G0), an aborted transaction whose writes stay (G1a),
    and two transactions that see each other's writes (G1c). The reference shows none."""
    def kinds(v):
        piece = scenario.run(v, chunk=0)
        return bool(piece["tables"]["g0"]), {a[4] for a in piece["tables"]["anomalies"]}

    assert kinds(FIRE)[0]  # G0
    assert scenario.G1A in kinds(module(AbortButKeep))[1]
    assert scenario.G1C in kinds(module(WritesFirst))[1]
    assert kinds("reference") == (False, set())


class WrongReplies(Single):  # answers txn_ok, but without the reads filled in (only the writes)
    async def on_txn(self, msg):
        self.run(msg)

    def reply(self, request, body):
        if body.get("type") == "txn_ok":
            body = dict(body, txn=[op for op in body["txn"] if op[0] == "w"])
        super().reply(request, body)


def test_replies_must_be_the_same_transaction_with_its_reads_filled_in():
    """The clients check every txn_ok, like Maelstrom: the same micro-operations in order, writes echoed,
    reads filled in. One that drops its reads is not an answer (the reference's always are)."""
    def answered(v):
        txns = scenario.run(v, chunk=0)["tables"]["txns"]
        return sum(t[scenario.TXN_OK] for t in txns) / len(txns)

    assert answered(module(WrongReplies)) < 0.8
    assert answered("reference") > 0.99


def test_reference_passes_every_goal():
    world = build_world("transactions", "reference", 4)
    res = results(world, "reference")
    assert len(res) >= 4 and all(all(r) for r in res)
    assert world.stage_index("reference") == 3  # Read committed


def test_partitions_are_random_but_the_first_cuts_a_node_off_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "isolate") for i in firsts)
    later = list(itertools.islice(scenario.incidents(4), 20))
    gaps = [b.t0 - a.t1 for a, b in zip(later, later[1:])]
    assert min(gaps) >= scenario.QUIET and len({i.cause for i in later}) > 1


def test_the_trace_stays_bounded():
    pieces = scenario.stream("reference")
    for _ in range(3):
        piece = next(pieces)
    sizes = {k: len(v) for k, v in piece["tables"].items()}
    pieces.close()
    assert sizes["txns"] < 4000 and sizes["msgs"] < 15000 and sizes["stale"] <= 600


# ------------------------------------------------------------- your code


def first():
    v = variant()
    return [r.ok for r in build_world("transactions", v, 1).runs[v].settled[0]]


@your_code(1, "writes reach the other nodes")
def test_stage1_replicates():
    assert first()[0]


@your_code(2, "every node catches up after a partition, with no dirty writes (G0)")
def test_stage2_catches_up():
    assert first()[:4] == [True, True, True, True]


@your_code(3, "no aborted, intermediate or circular reads (read committed)")
def test_stage3_read_committed():
    assert first() == [True] * 5


def test_a_second_picture_shows_what_the_clients_see():
    from live.views import adapter_for, set_view, views_for

    world = build_world("transactions", "reference", 1)
    assert views_for(world) == ["peers", "cluster", "lanes"]  # peers first: it opens with it
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights
    text, colour = frame.state
    assert text and len(text) <= 13


@starting_code
def test_the_peers_picture_shows_the_node_cut_off_and_who_replicates():
    from live.canvas import BLUE, EXTRA2, RED, plain
    from live.frame import compose
    from live.views import adapter_for

    def peers(v, times):
        world = build_world("transactions", v, 1)
        assert world.view == "peers"
        return world, [adapter_for(world).frame(v, t, 90) for t in times]

    calm = [k / 2 for k in range(10, 38)]  # 0:05 to 0:19
    world, given = peers("main", calm)
    _, solved = peers("reference", calm)
    assert not any(f.links for f in given)  # the starting code sends nothing to the others ...
    assert all(p.gauge == EXTRA2 for p in given[-1].peers)  # ... so every node falls behind
    assert all(len(f.links) == 3 and all(c == BLUE for *_, c in f.links) for f in solved)  # replication
    assert all(p.fill == 1.0 and p.outline == BLUE for f in solved for p in f.peers)
    for v in ("main", "reference"):
        world, (cut,) = peers(v, [25.0])
        assert cut.groups == [0, 0, 1] and {(0, 2), (1, 2)} <= {(a, b) for a, b, _ in cut.links}  # its links, cut
        assert cut.peers[2].label[0] == "n2"  # cut off: just its name; its links are cut (✕)
        assert "✕" in "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
    _, (cut,) = peers("reference", [25.0])
    assert any(2 in (a, b) for a, b, _ in cut.drops)  # what it sends is lost half way
    _, healed = peers("reference", [32.0])
    assert all(p.fill == 1.0 for p in healed[0].peers)  # caught up after the heal

    world, per_write = peers(PER_WRITE, [k / 10 for k in range(0, 600)])
    g1b = [p for f in per_write for p in f.peers if p.outline == RED]
    assert g1b and all(p.label[0] == p.short for p in g1b)  # intermediate reads: red, and just the name
    burst = max(sum(1 for a, b, *_ in f.flights if 2 in (a, b) and -1 not in (a, b)) for f in per_write[300:310])
    assert burst > 30  # its re-sends piled up during the cut, and flow once it heals
