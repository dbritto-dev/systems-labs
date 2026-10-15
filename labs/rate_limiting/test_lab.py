import itertools

from core.contract import load
from core.testing import build_world, starting_code, variant, your_code
from labs.rate_limiting import scenario

code = load("rate_limiting", variant(), scenario.NAMES)


# ------------------------------------------------------------- one limiter per stage


class NoLimit:
    def __init__(self, rate=20.0, burst=10.0, capacity=150.0):
        pass

    def allow(self, client, now):
        return True


class FixedWindow:
    def __init__(self, rate=20.0, burst=10.0, capacity=150.0):
        self.rate, self.counts = rate, {}

    def allow(self, client, now):
        key = (client, int(now))
        if self.counts.get(key, 0) >= self.rate:
            return False
        self.counts[key] = self.counts.get(key, 0) + 1
        return True


class TokenBucket:
    def __init__(self, rate=20.0, burst=10.0, capacity=150.0):
        self.rate, self.burst, self.buckets = rate, burst, {}

    def allow(self, client, now):
        tokens, last = self.buckets.get(client, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.buckets[client] = (tokens, now)
            return False
        self.buckets[client] = (tokens - 1, now)
        return True


def as_module(limiter):
    return type(limiter.__name__ + "Module", (), {"RateLimiter": limiter})


NO_LIMIT, FIXED, BUCKET = as_module(NoLimit), as_module(FixedWindow), as_module(TokenBucket)


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_the_first_flood_is_always_five_clients_at_twenty_seconds():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind, int(i.severity)) == (20.0, 35.0, "batch", 5) for i in first)
    later = list(itertools.islice(scenario.incidents(3), 30))
    assert {i.kind for i in later} == {"batch", "scraper", "sdk"} and all(i.cause for i in later)


def test_each_stage_fails_exactly_its_goals_on_every_big_flood():
    expected = {NO_LIMIT: (0, [True, False, False, False]),  # No limit
                FIXED: (1, [True, True, False, False]),  # Fixed window
                BUCKET: (2, [True, True, True, False])}  # Token bucket
    for module, (label, goals) in expected.items():
        world = build_world("rate_limiting", module, 4)
        assert world.stage_index(module) == label
        run = world.runs[module]
        floods = [i for i in sorted(run.settled) if int(run.incidents[i].severity) >= 3]
        assert len(floods) >= 3
        for i in floods:
            assert [r.ok for r in run.settled[i]][:4] == goals, (label, run.incidents[i])


def test_reference_passes_every_goal_on_every_flood():
    world = build_world("rate_limiting", "reference", 6)
    results = statuses(world, "reference")
    assert len(results) >= 5 and all(all(r) for r in results)
    assert world.stage_index("reference") == 3  # Bucket + fair share


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("rate_limiting", NO_LIMIT, 7)
    run = world.runs[NO_LIMIT]
    assert run.keys["requests"] == sorted(run.keys["requests"])
    assert run.keys["requests"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream(NO_LIMIT), 7)
    assert run.total("ask", 1e9) == sum(len(p["tables"]["requests"]) for p in pieces)


# ------------------------------------------------------------- your code


def flood(limiter, client, start, seconds, rate=1000.0):
    """Send `rate` requests/s for `seconds` from one client; return the times let through."""
    n = int(seconds * rate)
    return [start + k / rate for k in range(n) if limiter.allow(client, start + k / rate)]


@your_code(1, "RateLimiter keeps a flooding client to about `rate` per second")
def test_stage1_a_flood_is_limited():
    limiter = code.RateLimiter(rate=20.0, burst=10.0, capacity=150.0)
    let_through = flood(limiter, client=3, start=10.0, seconds=5.0)
    assert 90 <= len(let_through) <= 115  # about 20/s for 5 s


def test_never_refuses_a_client_that_stays_under_its_rate():
    """A guard, not a stage: the starting code already passes it, and every stage must keep passing it."""
    limiter = code.RateLimiter(rate=20.0, burst=10.0, capacity=150.0)
    assert all(limiter.allow(7, 100.0 + k * 0.2) for k in range(100))  # 5/s for 20 s


@your_code(2, "no burst at a window edge: at most rate + burst in any second")
def test_stage2_no_edge_burst():
    limiter = code.RateLimiter(rate=20.0, burst=10.0, capacity=150.0)
    edge = flood(limiter, client=1, start=5.95, seconds=0.1)  # 0.05 s each side of 6.0
    assert len(edge) <= 15  # a fixed window lets 40 through here


@your_code(3, "fair share: with 20 active clients, one client gets about 150/20 per second")
def test_stage3_fair_share():
    limiter = code.RateLimiter(rate=20.0, burst=10.0, capacity=150.0)
    for c in range(20):  # everyone is active
        limiter.allow(c, 9.0 + c * 0.05)
    let_through = []
    for k in range(5000):  # client 0 floods at 1000/s for 5 s; the others keep going at 1/s
        t = 10.0 + k / 1000
        if k % 200 == 0:
            for c in range(1, 20):
                limiter.allow(c, t)
        if limiter.allow(0, t):
            let_through.append(t)
    assert len(let_through) <= 55  # 7.5/s for 5 s, plus the burst; a plain bucket lets 110 through


@your_code(3, "the other clients are served through every flood")
def test_stage3_every_goal_on_the_first_flood():
    world = build_world("rate_limiting", variant(), 1)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 5


def test_a_second_picture_shows_the_topology():
    from live.views import adapter_for, set_view, views_for

    world = build_world("rate_limiting", "reference", 1)
    assert views_for(world) == ["relay", "cluster", "lanes"] and world.view == "relay"  # opens with relay
    set_view(world, "lanes")  # the checks below are about the lanes picture
    set_view(world, "cluster")
    frame = adapter_for(world).frame("reference", 25.0)  # in the first incident
    assert len(frame.nodes) >= 2 and frame.flights and frame.state[0]
    assert any(src == -1 for src, _, _, _ in frame.flights)  # requests come from the clients


@starting_code
def test_the_relay_picture_shows_the_gateway_holding_the_flood_back():
    from live.canvas import EXTRA3, RED
    from live.views import adapter_for, set_view

    def relay(v):
        world = build_world("rate_limiting", v, 1)
        set_view(world, "relay")
        return adapter_for(world).frame(v, 25.0, 100)  # in the first flood

    given, solved = relay("main"), relay("reference")
    assert given.users and given.flights and given.hops and given.relay.label[0] and given.state[0]
    # no limit: a flooding client gets through far over its share, and the backend fails (the door shuts)
    assert given.relay.gauge == RED and given.relay.fill == 1.0 and given.closed
    # with one, the gateway refuses the flood (429s, in their colour) and the backend holds
    assert solved.relay.gauge == EXTRA3 and "429" in solved.relay.label[0] and not solved.closed
