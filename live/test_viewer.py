"""The viewer's patterns without a terminal or a child process: commands, play states, toasts, the dirty flag."""

import pytest

from core.testing import build_world
from live import viewer as vw
from live.canvas import BLUE, Style


class FakeFeed:
    """Stands in for live.runner.Feed: the world already holds its run."""

    def __init__(self, variant: str = "reference") -> None:
        self.variant, self.restarted, self.error, self.loading = variant, False, None, None
        self.restarts = 0

    def tick(self, t: float) -> None:
        pass

    def restart(self) -> None:
        self.restarts += 1


@pytest.fixture
def v(monkeypatch):
    monkeypatch.setattr(vw, "mtimes", lambda lab: {"main.py": 1.0})
    world = build_world("retry_storm", "reference", 1)
    return vw.Viewer(world, FakeFeed(), "retry_storm", Style("none"))


def test_toasts_show_the_latest_message_until_it_expires():
    toasts = vw.Toasts()
    toasts.post("one", BLUE, until=10.0)
    toasts.post("two", BLUE, until=5.0)
    assert toasts.current(4.0) == ("two", BLUE)
    assert toasts.current(6.0) is None and toasts.last is None
    toasts.post("forever", BLUE)
    assert toasts.current(1e9) == ("forever", BLUE)


def test_every_key_is_a_command(v):
    assert set(vw.COMMANDS) >= {"q", "space", "v", "0", "r", "left", "right", "up", "down"}
    assert v.handle("space", 0.0) and v.state is vw.PAUSED
    assert v.handle("space", 0.0) and v.state is vw.PLAYING
    for _ in range(10):
        v.handle("up", 0.0)
    assert vw.SPEEDS[v.speed_i] == max(vw.SPEEDS)
    v.t = 30.0
    v.handle("left", 0.0)
    assert v.t == 25.0
    v.handle("x", 0.0)  # an unknown key does nothing
    assert v.handle("q", 0.0) is False


def test_the_view_key_switches_and_says_so(v):
    before = v.world.view
    v.handle("v", 100.0)
    assert v.world.view != before and v.toasts.current(101.0) and v.toasts.current(103.0) is None


def test_rerun_restarts_the_feed_and_0_goes_back_to_the_start(v):
    restarts = v.feed.restarts
    v.handle("r", 0.0)
    assert v.feed.restarts == restarts + 1 and v.reason == "reran"
    v.t = 40.0
    v.handle("0", 0.0)  # 0:00 is still in the window: just go back, no rerun
    assert v.t == 0.0 and v.feed.restarts == restarts + 1


def test_a_paused_idle_frame_is_not_composed_twice(v):
    v.handle("space", 0.0)  # paused
    first = v.frame(1.0, 110, 44)
    assert first is not None
    assert v.frame(1.05, 110, 44) is None  # nothing changed: no work
    assert v.frame(1.1, 92, 30) is not None  # the terminal was resized
    v.handle("right", 1.15)
    assert v.frame(1.2, 92, 30) is not None  # the playhead moved


def test_playing_frames_follow_the_clock(v):
    v.frame(1.0, 110, 44)
    assert v.frame(1.1, 110, 44) is not None and v.t > 0  # playing: the clock moves, every frame differs


def test_saving_a_file_reruns(v, monkeypatch):
    restarts = v.feed.restarts
    monkeypatch.setattr(vw, "mtimes", lambda lab: {"main.py": 2.0})
    v.update(10.0)
    assert v.feed.restarts == restarts + 1 and v.reason == "reran"
