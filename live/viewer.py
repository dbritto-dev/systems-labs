"""The live viewer's loop, in game-programming terms (https://gameprogrammingpatterns.com):

- **Game Loop**: `watch()` in __main__ calls `Viewer.frame(now, size)` then shows it, and feeds it keys.
- **State**: the playhead is `PLAYING` or `PAUSED`; each state knows how it advances the clock.
- **Command**: every key is a command in `COMMANDS` (key -> function), so keys can be rebound, listed and
  tested without a terminal.
- **Event Queue**: things that happen while the window runs (a rerun finished, an error, your file changed, a
  view switch) post a `Toast`, the one-line message over the footer; `Toasts` decides what shows, until when.
- **Dirty Flag**: a frame is composed only when something it shows changed (paused and idle: no work).
- **Debug overlay** (key d): frame time, frames a second, how many ticks drew, how far the simulation is ahead.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.contract import ROOT
from core.i18n import lang, screen_text
from live.canvas import BLUE, EXTRA2, MUTED, RED, RGB, Style
from live.frame import compose, spinner
from live.runner import Feed
from live.views import next_view, views_for

SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
SEEK = 5.0
STATUS_SECONDS = 4.0
FOREVER = float("inf")


def mtimes(lab: str, variant: str = "main") -> dict[str, float]:
    """Every file of the lab you might edit, in every language (labs/<lab>/*.py, labs/<lab>/es/*.py), and
    the file you gave with --variant, wherever it is."""
    out = {}
    folder = ROOT / "labs" / lab
    extra = [Path(variant).resolve()] if variant.endswith(".py") else []
    for p in [*folder.glob("*.py"), *folder.glob(f"{lang()}/*.py"), *extra]:
        if p.stem.isidentifier():  # not a Finder/iCloud copy like "main 2.py"
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return out


# ---------------------------------------------------------------- Event Queue: the messages over the footer


@dataclass(slots=True)
class Toast:
    text: str
    colour: RGB
    until: float  # monotonic seconds; FOREVER stays until something replaces it


class Toasts:
    """The message line: the latest message posted shows until it expires or a newer one replaces it."""

    def __init__(self) -> None:
        self.last: Toast | None = None

    def post(self, text: str, colour: RGB, until: float = FOREVER) -> None:
        self.last = Toast(text, colour, until)

    def clear(self) -> None:
        self.last = None

    def current(self, now: float) -> tuple[str, RGB] | None:
        if self.last is not None and now > self.last.until:
            self.last = None
        return (self.last.text, self.last.colour) if self.last else None


# ---------------------------------------------------------------- State: how the playhead moves


@dataclass(frozen=True, slots=True)
class PlayState:
    name: str  # the header's mode word key: "play" or "paused"
    moves: bool  # does the clock advance?


PLAYING = PlayState("play", True)
PAUSED = PlayState("paused", False)


# ---------------------------------------------------------------- the viewer


@dataclass
class Viewer:
    world: object
    feed: Feed
    lab: str
    style: Style
    t: float = 0.0
    speed_i: int = SPEEDS.index(1.0)
    state: PlayState = PLAYING
    reason: str = ""  # why the run restarted: "reran" (a file changed or r) or "restarted" (0)
    toasts: Toasts = field(default_factory=Toasts)
    seen: dict = field(default_factory=dict)
    next_poll: float = 0.0
    last: float | None = None  # the previous tick's time
    _drawn: tuple | None = None  # what the last composed frame showed (the dirty flag's memory)
    hud: bool = False  # the debug overlay (key d)
    _ms: float = 0.0  # the last composed frame's cost
    _shown: deque = field(default_factory=lambda: deque(maxlen=120))  # when frames were composed
    _ticks: int = 0
    _composed: int = 0

    def __post_init__(self) -> None:
        self.sc = screen_text()
        self.views = len(views_for(self.world))
        self.seen = mtimes(self.lab, self.feed.variant)
        self.toasts.post(self.sc.RUNNING_YOUR_CODE, MUTED)
        self.feed.restart()

    @property
    def run(self):
        return self.world.runs.get(self.feed.variant)

    def rerun(self, reason: str) -> None:
        self.reason = reason
        self.feed.restart()
        self.toasts.post(self.sc.RUNNING_YOUR_CODE, EXTRA2)

    # -- update

    def update(self, now: float) -> str:
        """Advance one tick: the feed, the events it raised, the clock, your files. Returns the header's mode."""
        dt, self.last = (0.0 if self.last is None else now - self.last), now
        sc, feed = self.sc, self.feed
        feed.tick(self.t)
        if feed.restarted:  # event: a new run arrived
            feed.restarted = False
            self.t = 0.0
            if self.reason:
                clock = f"{datetime.now():%H:%M:%S}"
                self.toasts.post(sc.RERAN_AT.format(reason=sc.REASONS[self.reason], clock=clock), BLUE,
                                 now + STATUS_SECONDS)
            else:
                self.toasts.clear()
        if feed.error:  # event: your code stopped
            self.toasts.post(sc.ERROR.format(error=feed.error), RED)
        run = self.run
        mode = self.state.name
        if run is not None and self.state.moves:
            self.t += dt * SPEEDS[self.speed_i]
            if self.t >= run.end - 0.05:  # caught up with the simulation: wait for it
                self.t = max(0.0, run.end - 0.05)
                mode = "simulating"
        elif run is None and self.state.moves:
            mode = "simulating"
        if now >= self.next_poll:  # event: you saved a file
            self.next_poll = now + 0.5
            current = mtimes(self.lab, self.feed.variant)
            if current != self.seen:
                self.seen = current
                self.rerun("reran")
        return mode

    # -- render (with the dirty flag)

    def frame(self, now: float, cols: int, rows: int) -> list[str] | None:
        """Update, then the frame to show, or None when it would look exactly like the last one."""
        mode = self.update(now)
        run, feed = self.run, self.feed
        self._ticks += 1
        shown = self.toasts.current(now)
        if self.hud and shown is None:
            recent = [s for s in self._shown if now - s <= 1.0]
            ahead = (run.end - self.t) if run is not None else 0.0
            shown = (self.sc.HUD.format(ms=self._ms, fps=len(recent), drawn=self._composed, ticks=self._ticks,
                                        ahead=ahead), MUTED)
        loading = feed.loading
        if loading and run is not None and not feed.error:  # a rerun: the old picture stays meanwhile
            step, waited = loading
            what = self.sc.LOADING_YOUR_CODE if step == "starting" else self.sc.SIMULATING_FIRST_MINUTE
            shown = (f"{spinner(waited)} {what}… {waited:.1f}s", EXTRA2)
        drawn = (self.t, cols, rows, mode, self.speed_i, shown, feed.error, loading, self.world.view,
                 feed.variant, None if run is None else (id(run), run.end, len(self.world.runs)))
        if drawn == self._drawn:
            return None
        self._drawn = drawn
        start = time.perf_counter()
        lines = compose(self.world, feed.variant, self.t, cols, rows, style=self.style, mode=mode,
                        speed=SPEEDS[self.speed_i], status=shown, error=feed.error, loading=loading, views=self.views)
        self._ms = (time.perf_counter() - start) * 1000
        self._shown.append(now)
        self._composed += 1
        return lines

    # -- input

    def handle(self, key: str, now: float) -> bool:
        """Run the key's command; False means quit."""
        command = COMMANDS.get(key)
        return True if command is None else command(self, key, now)


# ---------------------------------------------------------------- Command: one function per key


def quit_(v: Viewer, key: str, now: float) -> bool:
    return False


def toggle_pause(v: Viewer, key: str, now: float) -> bool:
    v.state = PAUSED if v.state is PLAYING else PLAYING
    return True


def switch_view(v: Viewer, key: str, now: float) -> bool:
    if v.views > 1:
        name = next_view(v.world)
        v.toasts.post(v.sc.VIEW.format(name=v.sc.VIEWS.get(name, name)), BLUE, now + 2)
    return True


def restart(v: Viewer, key: str, now: float) -> bool:
    run = v.run
    if key == "0" and run is not None and run.earliest == 0:
        v.t = 0.0  # 0:00 is still in the window: just go back
    else:
        v.rerun("reran" if key == "r" else "restarted")
    return True


def seek(v: Viewer, key: str, now: float) -> bool:
    run = v.run
    if run is not None:
        step = SEEK if key == "right" else -SEEK
        v.t = min(max(run.earliest, v.t + step), max(0.0, run.end - 0.05))
    return True


def toggle_hud(v: Viewer, key: str, now: float) -> bool:
    v.hud = not v.hud
    v._ticks = v._composed = 0  # count from now
    return True


def speed(v: Viewer, key: str, now: float) -> bool:
    v.speed_i = min(len(SPEEDS) - 1, v.speed_i + 1) if key == "up" else max(0, v.speed_i - 1)
    return True


Command = Callable[[Viewer, str, float], bool]
COMMANDS: dict[str, Command] = {
    "q": quit_, "esc": quit_, "ctrl-c": quit_,
    "space": toggle_pause,
    "v": switch_view,
    "0": restart, "r": restart,
    "left": seek, "right": seek,
    "up": speed, "down": speed,
    "d": toggle_hud,
}
