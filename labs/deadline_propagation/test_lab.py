import asyncio
import itertools

import pytest

from core.contract import load
from core.services import ServiceError
from core.testing import build_world, variant, your_code
from core.vtime import now, run_virtual
from labs.deadline_propagation import scenario
from live.canvas import RED
from labs.deadline_propagation.reference import HOP_TIMEOUT, MARGIN, DeadlineExceeded, expired, next_deadline

code = load("deadline_propagation", variant(), scenario.NAMES)


async def passed_down(hop, deadline):
    """Stage 1: the deadline goes down the chain, and each hop waits until its own; no checks."""
    await hop.work()
    if hop.last:
        return "ok"
    child = next_deadline(deadline)
    if child is None:
        return await hop.call_next(None, HOP_TIMEOUT)
    return await hop.call_next(child, deadline - now())


class PASSED:  # stands in for a main.py module at stage 1
    handle = staticmethod(passed_down)
    next_deadline, expired = staticmethod(next_deadline), staticmethod(expired)
    DeadlineExceeded, HOP_TIMEOUT, MARGIN = DeadlineExceeded, HOP_TIMEOUT, MARGIN


SEEDS = (1, 2, 3, 4)
# Goals: baseline, waste, served, overrun


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", SEEDS)
def test_per_hop_timeouts_keep_waiting_after_users_leave(seed):
    world = build_world("deadline_propagation", "main", 1, seed=seed)
    assert statuses(world, "main")[0] == [True, False, False, False]
    assert world.stage_index("main") == 0  # Per-hop timeouts


@pytest.mark.parametrize("seed", SEEDS)
def test_passing_the_deadline_stops_the_waiting_but_the_db_still_works_for_nobody(seed):
    world = build_world("deadline_propagation", PASSED, 1, seed=seed)
    assert statuses(world, PASSED)[0] == [True, False, False, True]
    assert world.stage_index(PASSED) == 1  # Deadline passed down


def test_reference_passes_every_goal_on_the_first_incidents():
    world = build_world("deadline_propagation", "reference", 6)
    results = statuses(world, "reference")
    assert len(results) >= 5 and all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Deadline + skip late work


def test_pieces_join_and_the_first_incident_is_fixed():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind, i.severity) == (20.0, 30.0, "db", 0.15) for i in first)
    a = list(itertools.islice(scenario.incidents(4), 30))
    gaps = [n.t0 - p.t1 for p, n in zip(a, a[1:])]
    assert min(gaps) >= scenario.QUIET and len({i.cause for i in a}) >= 4
    pieces = list(itertools.islice(scenario.stream("reference"), 2))
    starts = [r[1] for p in pieces for r in p["tables"]["requests"]]
    assert starts == sorted(starts) and starts[-1] < 120
    ids = [r[0] for p in pieces for r in p["tables"]["requests"]]
    assert len(set(ids)) == len(ids)


def test_both_pictures_show_the_chain():
    from live.views import adapter_for, set_view, views_for

    world = build_world("deadline_propagation", "main", 1)
    assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
    lane = adapter_for(world).frame("main", 27.0, 100)
    assert any(colour == RED and not waiting for colour, waiting in lane.users.values())  # left, still worked on
    set_view(world, "cluster")
    frame = adapter_for(world).frame("main", 27.0)
    assert len(frame.nodes) == 4 and frame.flights and frame.state[0]
    assert any(colour == RED for *_, colour in frame.flights)  # calls for users who left


# ------------------------------------------------------------- your code


class FakeHop:
    """One service for one request: records its work and its call to the next service."""

    def __init__(self, last: bool = False) -> None:
        self.name, self.last = ("db" if last else "api"), last
        self.worked = 0
        self.calls: list[tuple[float, float | None, float | None]] = []

    async def work(self) -> None:
        self.worked += 1
        await asyncio.sleep(0.010)

    async def call_next(self, deadline, timeout):
        self.calls.append((now(), deadline, timeout))
        return "ok"


def _handle(hop, deadline_in: float | None, start: float = 100.0):
    """Run code.handle at virtual time `start`, with a deadline that far ahead; (result, hop)."""

    async def main():
        await asyncio.sleep(start)
        deadline = None if deadline_in is None else now() + deadline_in
        try:
            return await code.handle(hop, deadline), deadline
        except ServiceError as exc:
            return exc, deadline

    return run_virtual(main())


@your_code(1, "next_deadline: the caller's deadline minus MARGIN; None stays None")
def test_stage1_next_deadline():
    assert code.next_deadline(10.0) == pytest.approx(10.0 - code.MARGIN)
    assert code.next_deadline(None) is None


@your_code(1, "handle sends next_deadline(deadline) down and waits no longer than its own deadline")
def test_stage1_handle_passes_the_deadline_down():
    hop = FakeHop()
    (result, deadline) = _handle(hop, 1.5)
    assert result == "ok" and hop.worked == 1 and len(hop.calls) == 1
    at, sent, timeout = hop.calls[0]
    assert sent == pytest.approx(deadline - code.MARGIN)
    assert sent - at - 1e-9 <= timeout <= deadline - at + 1e-9
    hop = FakeHop()
    assert _handle(hop, None)[0] == "ok" and hop.calls[0][1:] == (None, code.HOP_TIMEOUT)  # no deadline: as before


@your_code(1, "the chain gives up with the user: no caller waits after its user has left")
def test_stage1_no_overrun():
    world = build_world("deadline_propagation", variant(), 1)
    assert world.runs[variant()].settled[0][3].ok


@your_code(2, "expired: true at or past the deadline, never without one")
def test_stage2_expired():
    assert not code.expired(None, 1e9)
    assert not code.expired(10.0, 9.9)
    assert code.expired(10.0, 10.0) and code.expired(10.0, 11.0)


@your_code(2, "handle fails fast: no work and no call once the deadline has passed")
def test_stage2_handle_skips_late_work():
    hop = FakeHop()
    result, _ = _handle(hop, -0.5)  # the caller left half a second ago
    assert isinstance(result, ServiceError) and hop.worked == 0 and not hop.calls
    hop = FakeHop()
    result, _ = _handle(hop, code.MARGIN / 2)  # time for the work, but none left for the next service
    assert isinstance(result, ServiceError) and hop.worked == 1 and not hop.calls
    db = FakeHop(last=True)
    result, _ = _handle(db, 0.0)  # the db: the deadline is now, so no query
    assert isinstance(result, ServiceError) and db.worked == 0


@your_code(2, "no wasted work, and users are served as fast as the slow db allows")
def test_stage2_every_goal():
    world = build_world("deadline_propagation", variant(), 1)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 4
    assert world.stage_index(variant()) == 2
