"""A variation of the **lanes** view: **relay**. The users and the door are the same, and so is the server on
the right; in between stands a second server that passes requests on (a load balancer, a gateway, a queue,
an orchestrator). Two dotted lines: users → door → the relay, and the relay → the server.

    ○ ● ○ ○ ○        ┃     ┌────────┐            ┌────────┐
    ● ○ ○ ● ○ ·· • ··┃···•·│ ▬▬▬  ▪ │····• ·····│ ▬▬▬  ▪ │
    ○ ○ ● ○ ○        ┃     │▓▓▓▓▓▓▓▓│            │▓▓▓▓    │
                           4 balancers          DEGRADED s2

It draws a `RelayFrame` (a LaneFrame plus the relay box and the requests on the second line); a
`RelayAdapter` per lab makes one. The plain lanes view (live/views/lanes.py) is untouched.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BG, BLUE, DIM, RED, RGB, Canvas, mix
from live.views.base import Adapter, View, register
from live.views.lanes import GRID_COLS, IDLE, LINE, OUTLINE, LaneFrame, _server


@dataclass(slots=True)
class Relay:
    """The server in the middle: its own gauge, outline and a word under it."""

    label: tuple[str, RGB] = ("", DIM)  # e.g. "4 balancers"
    fill: float = 0.0
    gauge: RGB = BLUE
    outline: RGB = OUTLINE


@dataclass(slots=True)
class RelayFrame(LaneFrame):
    """A LaneFrame (users, door, the server on the right, its state) plus the relay in the middle.
    `flights` go from the users to the door (0..1), `hops` from the relay to the server (0..1)."""

    relay: Relay = field(default_factory=Relay)
    hops: list[tuple[float, RGB, bool]] = field(default_factory=list)  # (0..1, colour, big)


class RelayAdapter(Adapter):
    """Feeds the relay view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        """The picture at t, for a grid of `users` circles (as for the lanes view)."""


@register
class RelayView(View):
    name = "relay"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, RelayAdapter)
        draw_relay(cv, lambda n: adapter.frame(variant, t, n))


def draw_relay(cv: Canvas, make) -> None:
    h, cols = cv.rows, cv.cols
    body0, body1 = 0, h - 2  # the picture, then a row for the words under the two servers
    gr = max(3, body1 - body0 + 1)
    n = GRID_COLS * gr
    fr = make(n)
    ymid = (body0 + (body1 - body0 + 1) / 2) * 4
    xc = (cols - 7) * 2 + 1  # the server's centre, in dots (where the lanes view has it)
    gx = (1 + GRID_COLS * 2) * 2  # the users grid's right edge
    xg = gx + (xc - 8 - gx) * 0.38  # the door
    xm = xg + (xc - 8 - xg) * 0.5  # the relay's centre
    for i in range(n):  # the users, as in the lanes view
        r, c = body0 + i // GRID_COLS, 1 + (i % GRID_COLS) * 2
        col, busy = fr.users.get(i, (IDLE, False))
        cv.text(r, c, "●" if busy else "○", col)
    for x0, x1 in ((gx + 2, xg - 2), (xg + 2, xm - 9), (xm + 10, xc - 9)):  # the two lines (the door between)
        for x in range(int(x0), int(x1), 3):
            cv.dot(x, ymid, LINE, 0)
    if fr.closed:  # the door
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
    for j, (col, age) in enumerate(fr.outcomes[:8]):  # what happened, fading at the door
        cv.blob(xg - 4, ymid + (j - 3.5) * 3, mix(col, BG, age), 6, 1)
    for k, col, big in fr.hops:  # relay → server
        cv.blob(xm + 10 + (xc - 11 - xm - 10) * k, ymid, col, 6, 2 if big else 1)
    rl = fr.relay
    _server(cv, xm, body0 * 4 + 2, body1 * 4 + 2, rl.outline, rl.fill, rl.gauge)
    _server(cv, xc, body0 * 4 + 2, body1 * 4 + 2, fr.outline, fr.fill, fr.gauge)
    for (text, col), x in ((rl.label, xm), (fr.state, xc)):  # a word under each server
        at = round((x + 0.5) / 2 - len(text) / 2)
        cv.text(h - 1, max(0, min(at, cols - len(text))), text, col)
