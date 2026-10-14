import itertools
import math
from types import SimpleNamespace

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from labs.stream_windowing import reference as ref
from labs.stream_windowing import scenario
from live.canvas import BLUE, RED

code = load("stream_windowing", variant(), scenario.NAMES)


class _Names:  # what a main.py module exposes, besides Windower
    window_of = staticmethod(ref.window_of)
    WINDOW, ALLOWED_DELAY, ALLOWED_LATENESS = ref.WINDOW, ref.ALLOWED_DELAY, ref.ALLOWED_LATENESS


class WatermarkWindower(ref.Windower):
    """Stage 1: event time and a watermark; a late event for a closed window is dropped (counted)."""

    def on_event(self, event, now):
        self.max_seen = max(self.max_seen, event.time)
        start = ref.window_of(event.time)
        if start + ref.WINDOW <= self.watermark():
            self.dropped += 1
        else:
            self.windows[start] = self.windows.get(start, 0) + 1
        self.close_ready()

    def close_ready(self):
        wm = self.watermark()
        for start in sorted(self.windows):
            if start + ref.WINDOW <= wm:
                self.sink.emit(start, self.windows.pop(start))


class WATERMARK(_Names):  # stands in for a main.py module at stage 1
    Windower = WatermarkWindower


class WaitWindower(WatermarkWindower):
    """Stage 1 with a watermark as slow as the lateness: right, but the dashboard waits 30 s."""

    def watermark(self):
        return self.max_seen - ref.ALLOWED_DELAY - ref.ALLOWED_LATENESS


class WAIT(_Names):
    Windower = WaitWindower


class KeepWindower(ref.Windower):
    """Stage 2 without evict(): every window is kept forever, so the state keeps growing."""

    def too_late(self, start):
        return False


class KEEP(_Names):
    Windower = KeepWindower


SEEDS = (1, 2, 3, 4)
# Goals: baseline, exact, dropped, latency, state


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", SEEDS)
def test_processing_time_puts_late_events_in_the_wrong_window(seed):
    world = build_world("stream_windowing", "main", 2, seed=seed)
    assert statuses(world, "main")[0] == [False, False, False, True, True]
    assert world.stage_index("main") == 0  # Processing time


@pytest.mark.parametrize("seed", SEEDS)
def test_a_watermark_gets_calm_windows_right_but_drops_the_late_batch(seed):
    world = build_world("stream_windowing", WATERMARK, 2, seed=seed)
    assert statuses(world, WATERMARK)[0] == [True, False, False, True, True]
    assert world.stage_index(WATERMARK) == 1  # Event time + watermark


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_waiting_as_long_as_the_lateness_is_right_but_too_slow(seed):
    world = build_world("stream_windowing", WAIT, 2, seed=seed)
    assert statuses(world, WAIT)[0] == [True, True, True, False, True]
    assert world.stage_index(WAIT) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_keeping_every_window_lets_the_state_grow(seed):
    world = build_world("stream_windowing", KEEP, 2, seed=seed)
    assert statuses(world, KEEP)[0] == [True, True, True, True, False]
    assert world.stage_index(KEEP) == 1


def test_reference_passes_every_goal_on_the_first_incidents():
    world = build_world("stream_windowing", "reference", 6)
    results = statuses(world, "reference")
    assert len(results) >= 3 and all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Allowed lateness + updates


def test_pieces_join_and_the_first_incident_is_fixed():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 9)]
    assert all((i.t0, i.t1, i.kind, i.severity) == (20.0, 30.0, "offline", 18.0) for i in first)
    a = list(itertools.islice(scenario.incidents(4), 30))
    gaps = [n.t0 - p.t1 for p, n in zip(a, a[1:])]
    assert min(gaps) >= scenario.QUIET and len({i.kind for i in a}) == 4 and len({i.cause for i in a}) >= 8
    pieces = list(itertools.islice(scenario.stream("reference"), 2))
    arrived = [e[0] for p in pieces for e in p["tables"]["events"]]
    assert arrived == sorted(arrived) and 60 <= arrived[-1] < 120
    ids = [e[1] for p in pieces for e in p["tables"]["events"]]
    assert len(set(ids)) == len(ids)


def test_both_pictures_show_the_pipeline():
    from live.views import adapter_for, set_view, views_for

    world = build_world("stream_windowing", WATERMARK, 1)
    assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
    lane = adapter_for(world).frame(WATERMARK, 25.0, 100)
    assert lane.closed and lane.door_color == RED  # the watermark slams the door on the late batch
    assert any(colour == RED for colour, _ in lane.outcomes)
    set_view(world, "cluster")
    frame = adapter_for(world).frame(WATERMARK, 25.0)
    assert len(frame.nodes) == 7 and frame.flights and frame.drops and frame.state[0]

    world = build_world("stream_windowing", "reference", 1)
    lane = adapter_for(world).frame("reference", 25.0, 100)
    assert not lane.closed and any(colour == BLUE for colour, _ in lane.outcomes)  # updates


# ------------------------------------------------------------- your code


class FakeSink:
    def __init__(self) -> None:
        self.emits: list[tuple[float, int]] = []
        self.side: list = []

    def emit(self, start, count):
        self.emits.append((start, count))

    def side_output(self, event):
        self.side.append(event)


def feed(times: list[float]):
    """A Windower fed events with these event times (arriving in that order); (windower, sink)."""
    sink = FakeSink()
    w = code.Windower(sink)
    for i, t in enumerate(times):
        w.on_event(SimpleNamespace(id=i, time=t, source=0), max(times[: i + 1]) + 0.1)
    return w, sink


@your_code(1, "watermark: the largest event time seen minus ALLOWED_DELAY")
def test_stage1_watermark():
    w = code.Windower(FakeSink())
    assert w.watermark() == -math.inf
    w, _ = feed([3.0, 7.5, 5.0])
    assert w.watermark() == pytest.approx(7.5 - code.ALLOWED_DELAY)


@your_code(1, "events count in the window of their event time, emitted once the watermark passes its end")
def test_stage1_event_time_windows():
    w, sink = feed([1.0, 9.5, 10.5, 8.0, 11.0])  # 8.0 arrives late, but before the watermark passes 10
    assert sink.emits == []  # watermark 9.0: window [0, 10) is still open
    assert w.windows == {0.0: 3, 10.0: 2}
    w.on_event(SimpleNamespace(id=9, time=12.5, source=0), 12.6)  # watermark 10.5
    assert sink.emits == [(0.0, 3)]


@your_code(1, "a calm minute: every event is counted in its own window")
def test_stage1_calm_windows_right():
    world = build_world("stream_windowing", variant(), 1)
    assert world.runs[variant()].settled[0][0].ok


@your_code(2, "too_late: past the window's end plus ALLOWED_LATENESS, by the watermark")
def test_stage2_too_late():
    w, _ = feed([60.0])  # watermark 58
    assert not w.too_late(20.0)  # end 30 + 30 = 60 > 58
    assert w.too_late(10.0)  # end 20 + 30 = 50 <= 58


@your_code(2, "a late event updates its closed window; a later one goes to the side output; old windows are evicted")
def test_stage2_updates_side_output_and_evicts():
    w, sink = feed([1.0, 2.0, 15.0])  # watermark 13: [0, 10) is emitted with 2
    assert sink.emits == [(0.0, 2)] and 0.0 in w.windows
    w.on_event(SimpleNamespace(id=7, time=5.0, source=0), 15.2)  # late, within the lateness
    assert sink.emits[-1] == (0.0, 3)
    w.on_event(SimpleNamespace(id=8, time=45.0, source=0), 45.1)  # watermark 43: [0, 10) is past 40
    assert 0.0 not in w.windows and len(w.windows) <= 3
    late = SimpleNamespace(id=9, time=4.0, source=0)
    w.on_event(late, 45.2)
    assert sink.side == [late] and (0.0, 4) not in sink.emits  # parked, not counted


@your_code(2, "every goal: exact windows, nothing dropped silently, fast first results, bounded state")
def test_stage2_every_goal():
    world = build_world("stream_windowing", variant(), 2)
    assert [r.ok for r in world.runs[variant()].settled[0]] == [True] * 5
    assert world.stage_index(variant()) == 2
