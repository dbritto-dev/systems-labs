"""Lab stream_windowing: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import math

WINDOW = 10.0
ALLOWED_DELAY = 2.0
ALLOWED_LATENESS = 30.0


def window_of(t: float) -> float:
    """The start of the window that holds time t."""
    return math.floor(t / WINDOW) * WINDOW


class Windower:
    """Event-time windows with a watermark, allowed lateness with updates, and a side output."""

    def __init__(self, sink) -> None:
        self.sink = sink
        self.windows: dict[float, int] = {}
        self.fired: set[float] = set()
        self.max_seen = -math.inf
        self.dropped = 0

    def on_event(self, event, now: float) -> None:
        self.max_seen = max(self.max_seen, event.time)
        start = window_of(event.time)  # when it happened, not when it got here
        if self.too_late(start):
            self.sink.side_output(event)  # past any update: park it, never drop it silently
        else:
            self.windows[start] = self.windows.get(start, 0) + 1
            if start in self.fired:  # already on the dashboard: publish the corrected count
                self.sink.emit(start, self.windows[start])
        self.close_ready()
        self.evict()

    def watermark(self) -> float:
        return self.max_seen - ALLOWED_DELAY

    def close_ready(self) -> None:
        wm = self.watermark()
        for start in sorted(self.windows):
            if start + WINDOW <= wm and start not in self.fired:
                self.sink.emit(start, self.windows[start])  # the first result, as soon as it is due
                self.fired.add(start)  # ... but keep the window for late events

    def too_late(self, start: float) -> bool:
        return start + WINDOW + ALLOWED_LATENESS <= self.watermark()

    def evict(self) -> None:
        for start in [s for s in self.windows if self.too_late(s)]:
            del self.windows[start]  # bounded state: nothing can change this window any more
            self.fired.discard(start)
