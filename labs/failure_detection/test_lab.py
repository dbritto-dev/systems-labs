import functools
import itertools
from collections import deque

from core.contract import load
from core.net import Node
from core.testing import build_world, variant, your_code
from labs.failure_detection import reference as ref
from labs.failure_detection import scenario

code = load("failure_detection", variant(), scenario.NAMES + ("phi",))
ALIVE, SUSPECT, DEAD = ref.ALIVE, ref.SUSPECT, ref.DEAD
DETECT, FALSE, MSGS = range(3)  # goal order in the World


# ------------------------------------------------------------- one detector per stage, as people write them


class Fixed(Node):  # stage 0 as given: heartbeats to everyone, dead after a fixed timeout
    timeout = ref.TIMEOUT

    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.peers = [n for n in node_ids if n != node_id]
        self.status = {p: ALIVE for p in self.peers}
        self.last_heard = {p: 0.0 for p in self.peers}
        self.every(ref.HEARTBEAT, self.tick)

    async def tick(self):
        for p in self.peers:
            self.send(p, {"type": "heartbeat"})
        for p in self.peers:
            if self.now() - self.last_heard[p] > self.timeout:
                self.status[p] = DEAD

    async def on_heartbeat(self, msg):
        self.last_heard[msg.src] = self.now()
        self.status[msg.src] = ALIVE


class Patient(Fixed):  # the obvious fix: a 3 s timeout (no more false deaths, crashes found late)
    timeout = 3.0


class Phi(Fixed):  # stage 1: heartbeats to everyone, judged by phi accrual
    def __init__(self, node_id, node_ids):
        super().__init__(node_id, node_ids)
        self.intervals = {p: deque([ref.HEARTBEAT], maxlen=ref.WINDOW) for p in self.peers}

    async def tick(self):
        for p in self.peers:
            self.send(p, {"type": "heartbeat"})
        for p in self.peers:
            v = ref.phi(list(self.intervals[p]), self.now() - self.last_heard[p])
            if v >= ref.PHI_DEAD:
                self.status[p] = DEAD
            elif v >= ref.PHI_SUSPECT and self.status[p] == ALIVE:
                self.status[p] = SUSPECT

    async def on_heartbeat(self, msg):
        p = msg.src
        self.intervals[p].append(self.now() - self.last_heard[p])
        self.last_heard[p] = self.now()
        self.status[p] = ALIVE


class Direct(ref.Detector):  # SWIM without indirect probes: a lossy link is a dead node
    async def reach(self, peer, direct, indirect, k=ref.K):
        return await self.ping(peer, direct + indirect)


class NoSuspicion(ref.Detector):  # SWIM, dead as soon as the indirect probes fail: a slow node is buried
    async def probe(self, peer):
        if not await self.reach(peer, ref.PING_TIMEOUT, ref.INDIRECT_TIMEOUT):
            self.status[peer] = DEAD


def module(cls):
    return type(cls.__name__, (), {"Detector": cls})


FIXED, PATIENT, PHI, DIRECT, NO_SUSPICION = map(module, (Fixed, Patient, Phi, Direct, NoSuspicion))


def world_of(v, seed=1):
    return _first_minute(v, seed)


@functools.cache
def _first_minute(v, seed):
    return build_world("failure_detection", v, 1, seed=seed)


def results(world, v):
    run = world.runs[v]
    return [(run.incidents[i].kind, [r.ok for r in run.settled[i]]) for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


def test_a_fixed_timeout_buries_healthy_nodes_behind_the_lossy_links():
    piece = scenario.run("main", chunk=0)
    wrong = [d for d in piece["tables"]["deaths"] if d[3]]
    flaky = {frozenset(f"n{i}" for i in pair) for pair in scenario.FLAKY}
    assert len(wrong) >= 10
    assert all(frozenset((f"n{d[1]}", f"n{d[2]}")) in flaky for d in wrong)  # only across the bad links
    assert world_of("main").stage_index("main") == 0


def test_stage_variants_land_on_their_stage():
    # 0 fixed timeout (short: false deaths; long: crashes found late), 1 phi accrual, 2 SWIM
    for v, stage in ((FIXED, 0), (PATIENT, 0), (DIRECT, 0), (PHI, 1), ("reference", 2)):
        for seed in (1, 2, 3):
            world = world_of(v, seed=seed)
            assert world.stage_index(v) == stage, (getattr(v, "__name__", v), seed, results(world, v))


def test_each_goal_catches_its_mistake():
    (_, fixed), = results(world_of(FIXED), FIXED)
    assert fixed[DETECT] and not fixed[FALSE] and not fixed[MSGS]
    (_, patient), = results(world_of(PATIENT), PATIENT)
    assert not patient[DETECT] and patient[FALSE]
    (_, phi), = results(world_of(PHI), PHI)
    assert phi[DETECT] and phi[FALSE] and not phi[MSGS]


def test_phi_still_buries_a_node_behind_a_partial_partition():
    world = build_world("failure_detection", PHI, 2, seed=5)  # seed 5: a partial partition at 1:28
    res = results(world, PHI)
    assert [kind for kind, _ in res] == ["crash", "partial"]
    assert res[0][1] == [True, True, False] and not res[1][1][FALSE]


def test_without_suspicion_a_slow_node_is_declared_dead():
    world = build_world("failure_detection", NO_SUSPICION, 4, seed=6)  # seed 6: a slow node at 1:09
    res = dict(results(world, NO_SUSPICION))
    assert res["crash"][FALSE] and not res["slow"][FALSE]


def test_reference_passes_every_goal():
    for seed in (1, 4):
        world = build_world("failure_detection", "reference", 6, seed=seed)
        res = results(world, "reference")
        assert len(res) >= 4 and {kind for kind, _ in res} >= {"crash", "slow", "lossy"}
        assert all(all(r) for _, r in res), res
        assert world.stage_index("reference") == 2


def test_incidents_are_random_but_the_first_crashes_n2_at_twenty_seconds():
    firsts = [next(scenario.incidents(s)) for s in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "crash") for i in firsts)
    assert all(scenario.victim(i, s) == 2 for i, s in zip(firsts, (1, 2, 9)))
    later = list(itertools.islice(scenario.incidents(4), 40))
    assert {i.kind for i in later} == {"crash", "slow", "lossy", "partial"} and all(i.cause for i in later)
    assert len({scenario.victim(i, 4) for i in later}) == scenario.NODES
    cuts = [scenario.cut_off(i, 4) for i in later if i.kind == "partial"]
    assert cuts and all(2 <= len(c) <= 3 for c in cuts)


# ------------------------------------------------------------- your code


def first(v=None):
    v = v or variant()
    return [r.ok for r in world_of(v).runs[v].settled[0]]


@your_code(1, "phi(intervals, elapsed): a normal distribution's tail, as -log10")
def test_stage1_phi():
    steady = [0.25] * 50
    assert abs(code.phi(steady, 0.25) - 0.301) < 0.01  # half the heartbeats come later than the mean
    assert code.phi(steady, 0.55) > 8 > code.phi(steady, 0.3)  # MIN_STD = 0.05: 0.55 s is 6 spreads late
    noisy = [0.25, 0.5, 0.25, 0.75, 0.25, 0.5] * 10
    assert code.phi(noisy, 0.75) < 3 < code.phi(steady, 0.75)
    assert code.phi([], 5.0) == 0.0 and code.phi(steady, 60.0) > 100


@your_code(1, "phi accrual: the crash found in under 2.5 s, no healthy node declared dead")
def test_stage1_no_false_deaths():
    assert first()[:2] == [True, True]


@your_code(2, "SWIM: every goal of the first incident, under 10 messages per node per second")
def test_stage2_swim():
    assert first() == [True] * 3


# ------------------------------------------------------------- the pictures


def test_the_cluster_picture_shows_the_crash_found_and_the_lanes_what_clients_see():
    from live.canvas import EXTRA3, MUTED, RED
    from live.views import adapter_for, set_view, views_for

    world = build_world("failure_detection", "reference", 1)
    assert views_for(world) == ["cluster", "lanes"]  # cluster first: it opens with it
    cluster = adapter_for(world)
    assert cluster.frame("reference", 20.4).nodes[2] == MUTED  # crashed, nobody noticed yet
    assert cluster.frame("reference", 23.0).nodes[2] == RED  # declared dead
    assert RED not in cluster.frame("reference", 15.0).nodes  # nobody healthy declared dead
    set_view(world, "lanes")
    frame = adapter_for(world).frame("reference", 25.0, 90)
    assert frame.users or frame.flights or frame.outcomes
    text, colour = frame.state
    assert text and len(text) <= 13
    assert EXTRA3 not in [c for c, _ in frame.outcomes]  # no needless failover

    fixed = build_world("failure_detection", FIXED, 1)
    set_view(fixed, "lanes")
    seen = {c for t in range(5, 60) for c, _ in adapter_for(fixed).frame(FIXED, float(t), 90).outcomes}
    assert EXTRA3 in seen  # sessions moved off healthy nodes
