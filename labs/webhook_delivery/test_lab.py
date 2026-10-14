import heapq
import itertools
import random
from collections import deque

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.webhook_delivery import reference as R
from labs.webhook_delivery import scenario
from labs.webhook_delivery.api import Event, ok

LAB = "webhook_delivery"
code = load(LAB, variant(), (*scenario.NAMES, "Endpoint", "backoff", "ATTEMPT_TIMEOUT", "BACKOFF_CAP",
                             "MAX_IN_FLIGHT", "DISABLE_AFTER", "PROBE_EVERY", "MAX_ATTEMPTS"))
# Goals: baseline, lost, out of order, healthy p99, wasted work
BASELINE, LOST, ORDER, P99, WASTE = range(5)
FIRST = 2  # minutes until the first incident (0:20-0:45, endpoint #1 hangs) is judged


class SharedRetries:  # stage 1: one queue for everyone, a timeout, failures retried with backoff
    timeout = R.ATTEMPT_TIMEOUT

    def __init__(self, give_up, rng=None):
        self.give_up = give_up
        self.rng = rng or random.Random(0)
        self.queue = deque()
        self.retries = []

    def submit(self, ev, now):
        self.queue.append(ev)

    def next(self, now):
        if self.retries and self.retries[0][0] <= now:
            return heapq.heappop(self.retries)[2]
        return self.queue.popleft() if self.queue else None

    def done(self, ev, status, now):
        if not ok(status):
            heapq.heappush(self.retries, (now + R.backoff(ev.attempts, self.rng), ev.id, ev))


class RETRIES:
    Dispatcher = SharedRetries


class RETRIES_NO_TIMEOUT:  # retries, but every POST to a hanging endpoint waits the client's 30 s
    class Dispatcher(SharedRetries):
        timeout = None


def per_endpoint(endpoint):
    """The reference Dispatcher with another Endpoint."""

    class Dispatcher(R.Dispatcher):
        def submit(self, ev, now):
            ep = self.endpoints.get(ev.endpoint)
            if ep is None:
                ep = self.endpoints[ev.endpoint] = endpoint(self.rng)
            ep.queue.append(ev)

    return type(endpoint.__name__.upper(), (), {"Dispatcher": Dispatcher})


class Unordered(R.Endpoint):  # a queue, a cap and parking per endpoint, but no order per key
    def __init__(self, rng=None):
        super().__init__(rng)
        self.flying: set[int] = set()  # event ids in flight

    def pick(self, now):
        if len(self.flying) >= R.MAX_IN_FLIGHT or (self.parked and (self.flying or now < self.probe_at)):
            return None
        for ev in self.queue:
            if ev.id not in self.flying and self.retry_at.get(ev.id, 0.0) <= now:
                self.flying.add(ev.id)
                return ev
        return None

    def succeeded(self, ev, now):
        self.flying.discard(ev.id)
        super().succeeded(ev, now)

    def failed(self, ev, now):
        self.flying.discard(ev.id)
        return super().failed(ev, now)


class NeverParked(R.Endpoint):  # a queue, a cap and order per endpoint, but a dead endpoint keeps its 4 workers
    def failed(self, ev, now):
        self.sending.discard(ev.key)
        self.retry_at[ev.id] = now + R.backoff(ev.attempts, self.rng)
        return False


class NeverGivesUp(R.Endpoint):  # parks, but retries a malformed event forever: the rest of its order waits
    def failed(self, ev, now):
        self.sending.discard(ev.key)
        self.failures += 1
        if self.failures >= R.DISABLE_AFTER:
            self.parked = True
            self.probe_at = now + R.PROBE_EVERY
        self.retry_at[ev.id] = now + R.backoff(ev.attempts, self.rng)
        return False


UNORDERED, NO_PARKING, NO_GIVE_UP = (per_endpoint(e) for e in (Unordered, NeverParked, NeverGivesUp))


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


def by_kind(world, v) -> dict[str, list[list[bool]]]:
    run = world.runs[v]
    out: dict[str, list[list[bool]]] = {}
    for inc, result in zip(run.incidents, statuses(world, v)):
        out.setdefault(inc.kind, []).append(result)
    return out


# ------------------------------------------------------------- given behaviour


def test_starting_code_fires_once_loses_events_and_every_worker_hangs():
    for seed in (1, 2, 3):
        world = build_world(LAB, "main", FIRST, seed=seed)
        first = statuses(world, "main")[0]
        assert first[BASELINE] and not first[LOST]  # #1's events are given up
        assert not first[P99] and not first[WASTE]  # every worker waits 30 s on #1: everyone starves
        assert world.stage_index("main") == 0  # Fire once


def test_retries_lose_nothing_but_the_hanging_endpoint_eats_the_workers():
    for v in (RETRIES, RETRIES_NO_TIMEOUT):
        for seed in (1, 2, 3):
            world = build_world(LAB, v, FIRST, seed=seed)
            first = statuses(world, v)[0]
            assert first[LOST] and not first[P99] and not first[WASTE]
            assert world.stage_index(v) == 1  # Retries
    world = build_world(LAB, RETRIES, 6, seed=1)
    assert not by_kind(world, RETRIES)["down"][0][ORDER]  # a down endpoint: retries reorder its events


def test_a_queue_per_endpoint_without_order_per_key_delivers_out_of_order():
    for seed in (1, 2, 3, 4, 5, 6):
        world = build_world(LAB, UNORDERED, FIRST, seed=seed)
        first = statuses(world, UNORDERED)[0]
        assert first[LOST] and first[P99] and first[WASTE] and not first[ORDER]
        assert world.stage_index(UNORDERED) == 1


def test_a_queue_per_endpoint_never_parked_keeps_its_workers_waiting():
    for seed in (1, 2, 3):
        world = build_world(LAB, NO_PARKING, FIRST, seed=seed)
        assert statuses(world, NO_PARKING)[0] == [True, True, True, True, False]  # 4 of 24 workers: ~15%
        assert world.stage_index(NO_PARKING) == 1


def test_never_giving_up_a_malformed_event_blocks_the_rest_of_its_order():
    world = build_world(LAB, NO_GIVE_UP, 12, seed=7)
    assert world.stage_index(NO_GIVE_UP) == 2  # the first incident passes ...
    poison = by_kind(world, NO_GIVE_UP)["poison"][0]
    assert not poison[LOST]  # ... but events behind a malformed one never go out


def test_reference_passes_every_goal_for_ten_minutes():
    kinds = set()
    for seed in (1, 3):  # between them: every kind of incident
        world = build_world(LAB, "reference", 10, seed=seed)
        run = world.runs["reference"]
        results = statuses(world, "reference")
        assert len(results) >= 5 and all(all(r) for r in results)
        assert world.stage_index("reference") == 2  # Queue per endpoint
        kinds |= {i.kind for i in run.incidents}
    assert kinds >= {"hang", "down", "burst", "poison", "slow"}


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world(LAB, "reference", 7)
    run = world.runs["reference"]
    assert run.keys["events"] == sorted(run.keys["events"])
    assert run.keys["events"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    made = sum(len(p["tables"]["events"]) for p in pieces)
    assert run.total("made", 1e9) == made


# ------------------------------------------------------------- your code


def _event(eid: int, key: int, seq: int = 1, attempts: int = 0) -> Event:
    return Event(eid, 0, key, seq, "order.created", 0.0, attempts)


@your_code(1, "backoff: full jitter, between 0 and 0.5 s doubled per attempt, capped at BACKOFF_CAP")
def test_stage1_backoff():
    rng = random.Random(3)
    for n in range(1, 10):
        high = min(code.BACKOFF_CAP, 0.5 * 2 ** (n - 1))
        values = [code.backoff(n, rng) for _ in range(200)]
        assert all(0 <= v <= high for v in values), (n, min(values), max(values))
        assert max(values) - min(values) > high / 2  # jittered over the whole range


@your_code(1, "a timeout on every POST, and a failure is retried later instead of given up")
def test_stage1_retries_a_failure():
    gave_up = []
    d = code.Dispatcher(gave_up.append, random.Random(1))
    assert d.timeout == code.ATTEMPT_TIMEOUT
    ev = _event(1, 7)
    d.submit(ev, 0.0)
    assert d.next(0.0) is ev
    ev.attempts = 1
    d.done(ev, None, 0.1)  # no answer
    assert gave_up == []
    assert d.next(0.7) is ev  # back within its backoff (0 to 0.5 s)
    ev.attempts = 2
    d.done(ev, 200, 0.8)
    assert d.next(100.0) is None  # delivered: never again


@your_code(1, "the first incident (endpoint #1 hangs): no event lost")
def test_stage1_first_incident_loses_nothing():
    world = build_world(LAB, variant(), FIRST)
    assert statuses(world, variant())[0][LOST]


@your_code(2, "pick: at most MAX_IN_FLIGHT at once, one event per order, oldest first")
def test_stage2_pick_caps_and_keeps_each_order_in_order():
    ep = code.Endpoint(random.Random(1))
    ep.queue += [_event(1, 100, 1), _event(2, 100, 2)] + [_event(i, i) for i in range(3, 10)]
    picked = [ep.pick(0.0) for _ in range(code.MAX_IN_FLIGHT + 1)]
    assert [e.id for e in picked[:-1]] == [1, 3, 4, 5][:code.MAX_IN_FLIGHT]  # order.paid (2) waits for 1
    assert picked[-1] is None  # its share of the workers is taken
    ep.succeeded(picked[0], 0.1)
    assert ep.pick(0.1).id == 2  # now order 100's next event goes, before the newer ones


@your_code(2, "a failed event waits for its backoff, and the rest of its order waits behind it")
def test_stage2_a_retry_blocks_its_order():
    ep = code.Endpoint(random.Random(1))
    first, paid, other = _event(1, 100, 1, attempts=3), _event(2, 100, 2), _event(3, 200)
    ep.queue += [first, paid, other]
    assert ep.pick(0.0) is first
    assert ep.failed(first, 0.0) is False  # retried later, not given up
    assert ep.pick(0.0) is other  # order 100 waits: neither its retry nor order.paid go now
    assert ep.pick(0.0) is None
    assert ep.pick(code.BACKOFF_CAP + 1) is first


@your_code(2, "after DISABLE_AFTER failures in a row the endpoint is parked, probed, and replayed at once")
def test_stage2_park_probe_replay():
    ep = code.Endpoint(random.Random(1))
    ep.queue += [_event(i, i) for i in range(20)]
    now = 0.0
    for _ in range(code.DISABLE_AFTER):
        ev = ep.pick(now)
        ev.attempts += 1
        ep.failed(ev, now)
    assert ep.pick(now + 1.0) is None  # parked: nothing until the probe
    probe = ep.pick(now + code.PROBE_EVERY + 0.01)
    assert probe is not None and probe.attempts == 0  # a fresh event
    assert ep.pick(now + code.PROBE_EVERY + 0.02) is None  # one probe at a time
    probe.attempts += 1
    ep.succeeded(probe, now + code.PROBE_EVERY + 0.1)
    replay = [ep.pick(now + code.PROBE_EVERY + 0.2) for _ in range(code.MAX_IN_FLIGHT)]
    assert all(e is not None for e in replay)  # healthy again: the backlog goes now, retries included
    assert replay[0].id == 0  # oldest first


@your_code(2, "a malformed event is given up after MAX_ATTEMPTS while the endpoint works, never while parked")
def test_stage2_gives_up_poison_only():
    ep = code.Endpoint(random.Random(1))
    bad, good = _event(1, 100, attempts=code.MAX_ATTEMPTS - 1), _event(2, 200)
    ep.queue += [bad, good]
    ev = ep.pick(0.0)
    ev.attempts += 1
    assert ev is bad and ep.failed(bad, 0.0) is True
    assert bad not in ep.queue and ep.pick(0.0) is good


@your_code(2, "the first incident: every goal OK")
def test_stage2_first_incident_every_goal():
    world = build_world(LAB, variant(), FIRST)
    assert statuses(world, variant())[0] == [True] * 5
    assert world.stage_index(variant()) == 2


def test_two_pictures_the_cluster_first():
    from live.adapters.webhook_delivery import endpoint_node
    from live.canvas import RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v: str, t: float):
        world = worlds[v]
        set_view(world, "cluster")
        frame = adapter_for(world).frame(v, t)
        assert len(frame.nodes) == 25
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert frame.state[0] in text  # the line under the grid fits the smallest screen
        set_view(world, "lanes")
        lanes = adapter_for(world).frame(v, t, 100)
        text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
        assert lanes.state[0] in text
        set_view(world, "cluster")
        return frame, lanes

    worlds = {v: build_world(LAB, v, 1) for v in ("main", "reference")}
    assert views_for(worlds["main"]) == ["cluster", "lanes"] and worlds["main"].view == "cluster"  # cluster first
    one = endpoint_node(0)
    for v in ("main", "reference"):
        frame, _ = picture(v, 30.0)
        assert frame.nodes[one] == RED  # endpoint #1 hangs
    # The given code: every worker waits on #1 (dots sitting by it); the reference: a few, then none.
    given, _ = picture("main", 30.0)
    solved, _ = picture("reference", 30.0)
    waiting = lambda fr: sum(1 for _, dest, p, _ in fr.flights if dest == one and p == 0.85)  # noqa: E731
    assert waiting(given) >= 10 and waiting(solved) <= 1
    _, lanes = picture("main", 30.0)
    assert lanes.outline == RED  # half the pool or more stuck on one endpoint
