import itertools

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.overload import scenario
from labs.overload.reference import Request, overloaded, too_late

code = load("overload", variant(), (*scenario.NAMES, "MAX_QUEUE", "too_late", "overloaded"))


class Fifo:  # stage 0, as shipped
    def admit(self, request, queue_len, now):
        return True

    def drop(self, request, now):
        return False

    def newest_first(self, queue_len, now):
        return False


class Bounded(Fifo):  # stage 1
    def admit(self, request, queue_len, now):
        return queue_len < 200


class SkipLate(Bounded):  # stage 2
    def drop(self, request, now):
        return too_late(request, now)


class AdaptiveLifo(SkipLate):  # stage 3
    def newest_first(self, queue_len, now):
        return overloaded(queue_len)


def module(policy):
    """Stands in for a main.py module."""
    return type(policy.__name__, (), {"Policy": policy, "Request": Request})


FIFO, BOUNDED, SKIP, LIFO = (module(p) for p in (Fifo, Bounded, SkipLate, AdaptiveLifo))
# Goals: baseline, queue, waste, goodput, fast, recovered


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_starting_code_runs():
    world = build_world("overload", "main", 1)
    assert world.stage("main") is not None


def test_an_unbounded_fifo_queue_never_recovers():
    world = build_world("overload", FIFO, 4)
    results = statuses(world, FIFO)
    assert results[0] == [True, False, False, False, False, False]
    assert all(r == [False] * 6 for r in results[1:])  # still broken at the next incident: metastable
    assert world.stage(FIFO).label == "Unbounded FIFO"


def test_a_bounded_queue_still_works_for_users_who_left():
    world = build_world("overload", BOUNDED, 4)
    results = statuses(world, BOUNDED)
    assert results[0] == [True, True, False, False, False, False]
    assert world.stage(BOUNDED).label == "Bounded queue"


def test_skipping_late_requests_recovers_but_replies_are_slow():
    world = build_world("overload", SKIP, 6)
    results = statuses(world, SKIP)
    assert len(results) >= 4
    assert all(r == [True, True, True, True, False, True] for r in results)
    assert world.stage(SKIP).label == "Skip late requests"


def test_reference_passes_every_goal_on_the_first_eight_incidents():
    world = build_world("overload", "reference", 11)
    results = statuses(world, "reference")
    kinds = {i.kind for i in world.runs["reference"].incidents}
    assert len(results) >= 8 and kinds == {"spike", "capacity"}
    assert all(all(r) for r in results[:8])
    assert world.stage("reference").label == "Adaptive LIFO"


def test_pieces_join_and_totals_survive_forgetting():
    world = build_world("overload", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["tries"] == sorted(run.keys["tries"])
    assert run.keys["tries"][0] >= 60  # the first minute's raw rows are gone
    pieces = list(itertools.islice(scenario.stream("reference"), 7))
    sent = sum(len(p["tables"]["tries"]) for p in pieces)
    assert sum(run.total(f"try{k}", 1e9) for k in range(3)) == sent


def test_incidents_are_random_but_the_first_is_fixed():
    firsts = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "spike") for i in firsts)
    a = list(itertools.islice(scenario.incidents(4), 30))
    gaps = [n.t0 - p.t1 for p, n in zip(a, a[1:])]
    assert min(gaps) >= scenario.QUIET and {i.kind for i in a} == {"spike", "capacity"}


# ------------------------------------------------------------- your code


def _first(v):
    world = build_world("overload", v, 1)
    return [r.ok for r in world.runs[v].settled[0]]


@your_code(1, "Policy.admit rejects when the queue already holds MAX_QUEUE")
def test_stage1_bounded_queue():
    p = code.Policy()
    req = code.Request(1, 0.0, 0)
    assert p.admit(req, code.MAX_QUEUE - 1, 0.0) and not p.admit(req, code.MAX_QUEUE, 0.0)
    assert _first(variant())[1]  # the queue stayed bounded during the first spike


@your_code(2, "too_late: less than MARGIN left before the user gives up")
def test_stage2_too_late():
    req = code.Request(1, 10.0, 0)
    assert not code.too_late(req, 10.5)
    assert code.too_late(req, 10.95) and code.too_late(req, 11.2)
    assert _first(variant())[2:4] == [True, True]  # no waste, goodput back


@your_code(3, "overloaded: newest first while the queue is longer than LIFO_AT")
def test_stage3_adaptive_lifo():
    assert not code.overloaded(5) and code.overloaded(500)
    assert _first(variant()) == [True] * 6
