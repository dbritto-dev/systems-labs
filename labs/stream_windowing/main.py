"""Lab stream_windowing: YOUR FILE. Edit it and save; the live window reruns it.

A stream processor counts purchases per 10-second window for a live dashboard (and for
billing). Every event carries its event time: when the purchase happened, by the clock of
the phone or server that made it. Events reach the processor through a pipeline (a log
with three partitions), normally 0.05-1.5 s later and a little out of order. Each one calls
`Windower.on_event(event, now)`; you send results to the dashboard with
`self.sink.emit(start, count)`: the count of the window that starts at `start`. Emitting
the same window again replaces its count (an update).

Right now the processor counts by processing time: the window an event lands in is the
one open when it ARRIVES. Events that arrive a little late fall into the next window, and
when a batch comes in minutes late (phones back online, a lagging partition, a skewed
clock, a backfill), it all lands in the wrong window. The totals per window are wrong.

Do the stages in order, in this file:

  Stage 1  Event time with a watermark: put each event in the window of `event.time`.
           The watermark is the largest event time seen minus ALLOWED_DELAY; once it
           passes a window's end, emit that window and forget it (`close_ready`). An
           event for a window that has already closed is dropped and counted in
           `self.dropped`.
  Stage 2  Allowed lateness: keep a closed window ALLOWED_LATENESS seconds of watermark
           longer, and when a late event lands in it, count it and emit the corrected
           count (an update). An event later than that goes to the side output,
           `self.sink.side_output(event)`, so nothing is dropped silently; then forget
           windows that are that old (`evict`), so the state stays small.

Check yourself:  uv run pytest labs/stream_windowing
Peek at a solution (after trying!):  labs/stream_windowing/reference.py
"""

from __future__ import annotations

import math

WINDOW = 10.0  # seconds per window: [0, 10), [10, 20), ...
ALLOWED_DELAY = 2.0  # the watermark trails the largest event time seen by this much
ALLOWED_LATENESS = 30.0  # stage 2: a closed window is kept this long (in watermark time) for late events


def window_of(t: float) -> float:
    """The start of the window that holds time t."""
    return math.floor(t / WINDOW) * WINDOW


class Windower:
    """Counts events per window and emits each window's count to the dashboard.

    Contract:
      - `on_event(event, now)` is called once per event, in the order they arrive. `event.time`
        is its event time, `event.id` its id; `now` is when it arrived (processing time).
      - `self.sink.emit(start, count)` publishes a window's count; emitting the same `start`
        again replaces it (the dashboard shows the latest).
      - `self.sink.side_output(event)` parks an event that is too late for any window, for a
        batch job to reconcile later (stage 2).
      - `self.windows` is your state: window start -> count, for every window you still keep.
        The lab measures your state size as `len(self.windows)`.
    """

    def __init__(self, sink) -> None:
        self.sink = sink
        self.windows: dict[float, int] = {}  # window start -> count: the state
        self.fired: set[float] = set()  # stage 2: windows already emitted, kept for late events
        self.max_seen = -math.inf  # stage 1: the largest event time seen so far
        self.dropped = 0  # stage 1: late events dropped (a metric, not the events)

    def on_event(self, event, now: float) -> None:
        # Stage 1: count by event time instead:
        #     self.max_seen = max(self.max_seen, event.time)
        #     start = window_of(event.time)
        #     if start + WINDOW <= self.watermark(): the window has closed: self.dropped += 1
        #     else: self.windows[start] = self.windows.get(start, 0) + 1
        #     then self.close_ready()
        # Stage 2: if self.too_late(start): self.sink.side_output(event) instead of counting it;
        #          a late event for a window in self.fired: count it, then emit its new count;
        #          after close_ready(), call self.evict().
        for start in sorted(self.windows):  # processing time: close what the clock has passed
            if start + WINDOW <= now:
                self.sink.emit(start, self.windows.pop(start))
        start = window_of(now)  # the window open when it ARRIVED, not when it happened
        self.windows[start] = self.windows.get(start, 0) + 1

    def watermark(self) -> float:
        """Stage 1. How far event time has got, minus the delay we allow for stragglers:
        `self.max_seen - ALLOWED_DELAY`. No event seen yet: -math.inf."""
        raise NotImplementedError("TODO stage 1: watermark()")

    def close_ready(self) -> None:
        """Stage 1. Emit every window whose end (start + WINDOW) is at or before the watermark,
        oldest first, and remove it from self.windows.

        Stage 2: do not remove it: emit it once, add its start to self.fired, and keep it for
        late events (evict() removes it later)."""
        raise NotImplementedError("TODO stage 1: close_ready()")

    def too_late(self, start: float) -> bool:
        """Stage 2. True when the window starting at `start` is past its allowed lateness:
        its end plus ALLOWED_LATENESS is at or before the watermark."""
        raise NotImplementedError("TODO stage 2: too_late(start)")

    def evict(self) -> None:
        """Stage 2. Forget every window that is too_late(): remove it from self.windows and
        self.fired. Late events for it will go to the side output."""
        raise NotImplementedError("TODO stage 2: evict()")
