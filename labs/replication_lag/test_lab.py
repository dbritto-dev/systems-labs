import itertools
import random

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.replication_lag import scenario
from labs.replication_lag.scenario import Replica

code = load("replication_lag", variant(), scenario.NAMES)


class AnyRouter:  # stage 0 as given: any replica that is up
    def __init__(self, rng=None):
        self.rng = rng or random.Random(0)

    def wrote(self, session, lsn):
        pass

    def pick(self, session, key, replicas):
        up = [r.name for r in replicas if r.up]
        return self.rng.choice(up) if up else "primary"

    def saw(self, session, key, name, lsn):
        pass


class RywRouter(AnyRouter):  # stage 1: read your writes, but nothing for monotonic reads
    def __init__(self, rng=None):
        super().__init__(rng)
        self.written = {}

    def wrote(self, session, lsn):
        self.written[session] = max(self.written.get(session, 0), lsn)

    def pick(self, session, key, replicas):
        fresh = [r.name for r in replicas if r.up and r.lsn >= self.written.get(session, 0)]
        return self.rng.choice(fresh) if fresh else "primary"


class PrimaryRouter(AnyRouter):  # always the primary: never wrong, but no replica takes a read
    def pick(self, session, key, replicas):
        return "primary"


class ANY:
    Router = AnyRouter


class RYW:
    Router = RywRouter


class PRIMARY:
    Router = PrimaryRouter


RYW_GOAL, MONO_GOAL, PRIMARY_GOAL = range(3)


def statuses(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_first_incident_is_r2_falling_six_seconds_behind_at_0_20():
    piece = scenario.run(ANY, chunk=0)
    t0, t1, kind, severity, cause = piece["incidents"][0]
    assert (t0, t1, kind, severity) == (20.0, 30.0, "behind", 6.0)
    assert scenario.target(scenario.FIRST) == 2
    before = [row for row in piece["tables"]["lag"] if 10 <= row[0] < 20]
    during = [row for row in piece["tables"]["lag"] if 27 <= row[0] < 30]
    assert max(max(row[1]) for row in before) < 0.5
    assert min(row[1][1] for row in during) > 5  # r2, 6 s behind


def test_any_replica_misses_own_writes_and_goes_back_in_time():
    world = build_world("replication_lag", ANY, 3)
    results = statuses(world, ANY)
    assert results[0][1] == [False, False, True]
    assert all(not ok[RYW_GOAL] and ok[PRIMARY_GOAL] for _, ok in results)
    assert world.stage_index(ANY) == 0


def test_always_the_primary_is_never_wrong_but_fails_the_primary_goal():
    world = build_world("replication_lag", PRIMARY, 2)
    results = statuses(world, PRIMARY)
    assert results and all(ok == [True, True, False] for _, ok in results)
    assert world.stage_index(PRIMARY) == 0


def test_read_your_writes_alone_still_goes_back_in_time_when_a_replica_lags():
    world = build_world("replication_lag", RYW, 4, seed=3)
    results = statuses(world, RYW)
    behind = [ok for kind, ok in results if kind == "behind"]
    assert len(behind) >= 3 and all(ok == [True, False, True] for ok in behind)
    assert all(ok[RYW_GOAL] and ok[PRIMARY_GOAL] for _, ok in results)
    assert world.stage_index(RYW) == 1


def test_reference_passes_every_goal_on_every_kind_of_incident():
    results = []
    for seed in (1, 3):
        world = build_world("replication_lag", "reference", 4, seed=seed)
        results += statuses(world, "reference")
        assert world.stage_index("reference") == 2
    assert {kind for kind, _ in results} == {"behind", "restart", "spike"}
    assert len(results) >= 8 and all(all(ok) for _, ok in results)


def test_pieces_join_in_order_and_the_trace_stays_bounded():
    world = build_world("replication_lag", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["reads"] == sorted(run.keys["reads"])
    assert run.keys["reads"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    reads = sum(sum(1 for r in p["tables"]["reads"] if r[4]) for p in pieces)
    assert run.total("served", 1e9) == reads


# ------------------------------------------------------------- your code


def _replicas(*lsns):
    return [Replica(f"r{i + 1}", lsn, True) for i, lsn in enumerate(lsns)]


@your_code(1, "Router.pick reads a session's own write: a replica that has it, else the primary")
def test_stage1_pick_reads_your_writes():
    router = code.Router(rng=random.Random(1))
    router.wrote(7, 50)
    picks = {router.pick(7, "u7", _replicas(10, 60, 49, 50)) for _ in range(100)}
    assert picks == {"r2", "r4"}
    assert router.pick(7, "u7", _replicas(10, 20, 30, 40)) == "primary"
    assert len({router.pick(8, "u8", _replicas(10, 20, 30, 40)) for _ in range(100)}) == 4  # no write yet


@your_code(1, "nobody misses their own write, and the primary takes few reads")
def test_stage1_goals_pass():
    world = build_world("replication_lag", variant(), 1)
    first = world.runs[variant()].settled[0]
    assert first[RYW_GOAL].ok and first[PRIMARY_GOAL].ok


@your_code(2, "Router.pick never reads older than what the session saw of that key")
def test_stage2_pick_never_goes_back():
    router = code.Router(rng=random.Random(1))
    router.saw(3, "p0", "r1", 80)
    picks = {router.pick(3, "p0", _replicas(79, 80, 90, 10)) for _ in range(100)}
    assert picks == {"r2", "r3"}
    assert router.pick(3, "p0", _replicas(1, 2, 3, 4)) == "primary"
    assert len({router.pick(3, "p1", _replicas(1, 2, 3, 4)) for _ in range(100)}) == 4  # another key


@your_code(2, "every goal passes: own writes, never back in time, primary ≤ 35%")
def test_stage2_every_goal_passes():
    world = build_world("replication_lag", variant(), 2)
    run = world.runs[variant()]
    assert all(all(r.ok for r in run.settled[i]) for i in run.settled if all(run.settled[i]))
    assert world.stage_index(variant()) == 2


def test_a_second_picture_shows_what_the_clients_see():
    from live.canvas import RED
    from live.views import adapter_for, set_view, views_for

    world = build_world("replication_lag", "reference", 1)
    assert views_for(world) == ["fanout", "cluster", "lanes"] and world.view == "fanout"  # opens with fanout
    set_view(world, "cluster")  # the checks below are about the cluster picture
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)  # in the middle of the first incident
    assert frame.users or frame.flights or frame.outcomes
    text, colour = frame.state
    assert text and len(text) <= 13
    assert RED not in [c for c, _ in frame.outcomes]  # reads go to a fresh replica: green, never stale (red)


def test_the_fanout_picture_shows_where_each_read_goes():
    from live.canvas import RED
    from live.views import adapter_for, set_view

    def fan(v, t: float):
        world = build_world("replication_lag", v, 1)
        set_view(world, "fanout")
        return adapter_for(world).frame(v, t, 100)

    given, solved = fan("main", 27.0), fan("reference", 27.0)  # r2 is ~6 s behind (0:20-0:30)
    assert len(given.leaves) == 5 and all(0 < len(leaf.label[0]) <= 13 for leaf in given.leaves)  # wide screens
    assert all(len(leaf.short or leaf.label[0]) <= 9 for leaf in given.leaves)  # and small ones
    assert "r2" in given.leaves[2].label[0] and given.leaves[2].outline != given.leaves[1].outline  # r2 is behind
    # Reading any replica hands out stale reads from r2 (red); the solution sends hardly any reads there.
    assert any(c == RED and j == 2 for j, _, c, _ in given.hops) and given.relay.outline == RED
    assert not any(c == RED for _, _, c, _ in solved.hops) and solved.relay.outline != RED
    assert solved.leaves[2].fill < given.leaves[2].fill
    assert solved.relay.fill <= 0.35  # the router keeps the primary's share under the limit
