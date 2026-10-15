"""A variation of the **lanes** view: **fan-out**. The users and the door are the same; in the middle
stands a relay server (an orchestrator, a dispatcher, a balancer) and on the right, instead of one
server, a few small ones it calls, each with its name, its own gauge and its own colour. Requests fly
from the relay to the one they go to, and replies or undos can fly back.

    ○ ● ○ ○ ○        ┃     ┌────────┐ ···•·· ┌────┐ payments
    ● ○ ○ ● ○ ·· • ··┃···•·│ ▬▬▬  ▪ │ ·•···· ┌────┐ stock
    ○ ○ ● ○ ○        ┃     │▓▓▓▓▓▓▓▓│ ··◀··· └────┘ shipping
                          orchestrator          HALF DONE

It draws a `FanoutFrame` (a LaneFrame plus the relay and its servers); a `FanoutAdapter` per lab makes
one. The plain lanes view (live/views/lanes.py) and the relay variation are untouched.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BG, BLUE, DIM, RED, RGB, WHITE, Canvas, mix
from live.views.base import Adapter, View, register
from live.views.lanes import GRID_COLS, IDLE, LINE, OUTLINE, LaneFrame, _server
from live.views.lanes_relay import Relay

LABEL_COLS = 10  # room for each small server's name, right of it


@dataclass(slots=True)
class Leaf:
    """One of the small servers on the right."""

    label: tuple[str, RGB] = ("", WHITE)  # its name, right of it (or a word about it: "#1 hangs")
    fill: float = 0.0  # its gauge, 0..1, filling from the left
    gauge: RGB = BLUE
    outline: RGB = OUTLINE


@dataclass(slots=True)
class FanoutFrame(LaneFrame):
    """A LaneFrame (users, door, outcomes, state) plus the relay in the middle and the small servers on the
    right. `flights` go from the users to the door; `hops` from the relay to a server, or back."""

    relay: Relay = field(default_factory=Relay)
    leaves: list[Leaf] = field(default_factory=list)
    hops: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (leaf, 0..1, colour, back)


class FanoutAdapter(Adapter):
    """Feeds the fan-out view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float, users: int) -> FanoutFrame:
        """The picture at t, for a grid of `users` circles (as for the lanes view)."""


@register
class FanoutView(View):
    name = "fanout"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, FanoutAdapter)
        draw_fanout(cv, lambda n: adapter.frame(variant, t, n))


def _leaf(cv: Canvas, x0: float, x1: float, y0: float, y1: float, leaf: Leaf) -> None:
    """A small server: a case, and a gauge that fills from the left."""
    y0, y1 = int(y0), int(y1)
    cv.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], leaf.outline, 2)
    right = x0 + 2 + (x1 - x0 - 4) * max(0.0, min(1.0, leaf.fill))
    for y in range(y0 + 2, y1 - 1, 2):
        for x in range(int(x0 + 2), int(right), 2):
            cv.dot(x + (y & 1), y, leaf.gauge, 1)


def draw_fanout(cv: Canvas, make) -> None:
    h, cols = cv.rows, cv.cols
    body0, body1 = 0, h - 2
    gr = max(3, body1 - body0 + 1)
    n = GRID_COLS * gr
    fr = make(n)
    ymid = (body0 + (body1 - body0 + 1) / 2) * 4
    gx = (1 + GRID_COLS * 2) * 2  # the users grid's right edge, in dots
    lx1 = (cols - LABEL_COLS - 1) * 2  # the small servers: their right edge ...
    lx0 = lx1 - 12  # ... and left edge
    xg = gx + (lx0 - gx) * 0.3  # the door
    xm = xg + (lx0 - 10 - xg) * 0.55  # the relay's centre
    for i in range(n):  # the users, as in the lanes view
        r, c = body0 + i // GRID_COLS, 1 + (i % GRID_COLS) * 2
        col, busy = fr.users.get(i, (IDLE, False))
        cv.text(r, c, "●" if busy else "○", col)
    for x0, x1 in ((gx + 2, xg - 2), (xg + 2, xm - 9)):  # users → door → relay
        for x in range(int(x0), int(x1), 3):
            cv.dot(x, ymid, LINE, 0)
    if fr.closed:
        for dx in (0, 1):
            cv.line([(xg + dx, body0 * 4), (xg + dx, body1 * 4 + 3)], fr.door_color or RED, 2)
    else:
        for y in range(int(body0 * 4), int(body1 * 4 + 4), 3):
            cv.dot(xg, y, fr.door_color or DIM, 1)
    for i, k, col, big in fr.flights:  # users → door
        y0 = (body0 + i // GRID_COLS) * 4 + 2
        x = gx + (xg - 3 - gx) * k
        y = y0 + (ymid - y0) * min(1.0, k / 0.2)
        cv.blob(x, y, col, 6, 2 if big else 1)
    for j, (col, age) in enumerate(fr.outcomes[:8]):
        cv.blob(xg - 4, ymid + (j - 3.5) * 3, mix(col, BG, age), 6, 1)

    # The small servers, stacked; a dotted line from the relay to each.
    k = max(1, len(fr.leaves))
    top, bottom = body0 * 4 + 1, body1 * 4 + 3
    slot_h = (bottom - top) / k
    mids = []
    sx = xm + 10  # where the lines leave the relay
    for j, leaf in enumerate(fr.leaves):
        y0 = top + j * slot_h + 1
        y1 = top + (j + 1) * slot_h - 4  # a gap between them
        if y1 - y0 < 5:  # never thinner than a gauge
            y1 = y0 + 5
        ym = (y0 + y1) / 2
        mids.append(ym)
        steps = max(1, int((lx0 - 2 - sx) / 3))
        for s in range(steps + 1):
            p = s / steps
            cv.dot(sx + (lx0 - 2 - sx) * p, ymid + (ym - ymid) * p, LINE, 0)
        _leaf(cv, lx0, lx1, y0, y1, leaf)
        text, col = leaf.label
        cv.text(min(h - 2, int(ym // 4)), lx1 // 2 + 2, text[:LABEL_COLS - 1], col)
    for j, p, col, back in fr.hops:  # relay ⇄ a small server
        if 0 <= j < len(mids):
            p = 1 - p if back else p
            cv.blob(sx + (lx0 - 3 - sx) * p, ymid + (mids[j] - ymid) * p, col, 6, 1)
    rl = fr.relay
    _server(cv, xm, body0 * 4 + 2, body1 * 4 + 2, rl.outline, rl.fill, rl.gauge)
    for (text, col), x in ((rl.label, xm), (fr.state, (lx0 + lx1) / 2)):
        at = round((x + 0.5) / 2 - len(text) / 2)
        cv.text(h - 1, max(0, min(at, cols - len(text))), text, col)
