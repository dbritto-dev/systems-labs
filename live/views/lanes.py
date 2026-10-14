"""The **lanes** view: the users as a grid of circles on the left (○ idle, ● waiting, coloured by how much extra
work they cost), one dotted line with requests in flight to the door in front of the server (a gateway, a cache,
a queue), and the server as a rectangle with three drive bays and a gauge on the right. It draws a `LaneFrame`;
a `LaneAdapter` per lab (live/adapters/<lab>.py) makes one from that lab's World.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BG, BLUE, DIM, GREEN, RED, RGB, Canvas, mix
from live.views.base import Adapter, View, register

GRID_COLS = 5
IDLE: RGB = (52, 58, 70)
LINE: RGB = (46, 52, 64)
OUTLINE: RGB = (130, 140, 155)


@dataclass(slots=True)
class LaneFrame:
    """Everything the lanes view draws at one moment."""

    users: dict[int, tuple[RGB, bool]] = field(default_factory=dict)  # circle -> (colour, waiting)
    flights: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (circle, 0..1 to the door, colour, big)
    outcomes: list[tuple[RGB, float]] = field(default_factory=list)  # (colour, 0..1 faded): what happened at the door
    closed: bool = False  # the door: a solid bar when closed, dotted when open
    door_color: RGB | None = None  # default: red when closed, dim when open
    fill: float = 0.0  # the server's gauge, 0..1
    gauge: RGB = BLUE
    outline: RGB = OUTLINE
    state: tuple[str, RGB] = ("HEALTHY", GREEN)  # (text, colour) under the server


class LaneAdapter(Adapter):
    """Feeds the lanes view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        """The picture at t, for a grid of `users` circles (put request i in circle `slot(i, users)`)."""


def slot(rid: int, n: int) -> int:
    """Which circle a request belongs to: a hash, so requests that run at the same time land far apart."""
    return ((rid * 2654435761) >> 7 ^ rid * 40503) % n if n > 0 else 0


def _server(cv: Canvas, xc: float, y0: float, y1: float, rgb: RGB, fill: float, fill_rgb: RGB) -> None:
    """The server: a rectangle with three drive bays and a status light at the top, and a gauge inside that
    fills from the bottom."""
    rx = 8
    x0, x1 = xc - rx, xc + rx
    y0, y1 = int(y0), int(y1)
    cv.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], rgb, 2)  # the case
    for k in range(3):  # drive bays across the top
        yb = y0 + 3 + k * 3
        cv.line([(x0 + 3, yb), (x1 - 6, yb)], rgb, 2)
        cv.dot(x1 - 3, yb, rgb, 2)  # a status light per bay
    cv.line([(x0, y0 + 11), (x1, y0 + 11)], rgb, 2)  # the bays end here; the gauge is below
    inner = (y1 - 2) - (y0 + 13)
    top = (y1 - 2) - inner * max(0.0, min(1.0, fill))
    y = y1 - 2
    while y > top:
        for x in range(int(x0 + 2), int(x1 - 1), 2):
            cv.dot(x + (y & 1), y, fill_rgb, 1)
        y -= 2


@register
class LanesView(View):
    name = "lanes"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, LaneAdapter)
        draw_lanes(cv, lambda n: adapter.frame(variant, t, n))


def draw_lanes(cv: Canvas, make) -> None:
    """Lay the picture out on the canvas; `make(users)` gives the LaneFrame for a grid of that many circles."""
    h, cols = cv.rows, cv.cols
    body0, body1 = 0, h - 2  # the picture, then a row for the server's state
    gr = max(3, body1 - body0 + 1)
    n = GRID_COLS * gr
    lane = make(n)
    ymid = (body0 + (body1 - body0 + 1) / 2) * 4
    xc = (cols - 7) * 2 + 1  # the server's centre, in dots
    xg = xc - 8 - 12  # the door, in dots
    for i in range(n):  # the users: ○ idle, ● waiting (its colour: how much extra work)
        r, c = body0 + i // GRID_COLS, 1 + (i % GRID_COLS) * 2
        col, busy = lane.users.get(i, (IDLE, False))
        cv.text(r, c, "●" if busy else "○", col)
    gx = (1 + GRID_COLS * 2) * 2  # the grid's right edge, in dots
    for x in range(gx + 2, int(xg) - 2, 3):  # one dotted line from the users to the door
        cv.dot(x, ymid, LINE, 0)
    if lane.closed:  # the door: a solid bar when closed, dotted when open
        for dx in (0, 1):
            cv.line([(xg + dx, body0 * 4), (xg + dx, body1 * 4 + 3)], lane.door_color or RED, 2)
    else:
        for y in range(int(body0 * 4), int(body1 * 4 + 4), 3):
            cv.dot(xg, y, lane.door_color or DIM, 1)
    for i, k, col, big in lane.flights:  # requests in flight: leave a user, join the line, reach the door
        y0 = (body0 + i // GRID_COLS) * 4 + 2
        x = gx + (xg - 3 - gx) * k
        y = y0 + (ymid - y0) * min(1.0, k / 0.2)
        cv.blob(x, y, col, 6, 2 if big else 1)
    for j, (col, age) in enumerate(lane.outcomes[:8]):  # what happened at the door, fading
        cv.blob(xg - 4, ymid + (j - 3.5) * 3, mix(col, BG, age), 6, 1)
    _server(cv, xc, body0 * 4 + 2, body1 * 4 + 2, lane.outline, lane.fill, lane.gauge)
    text, col = lane.state
    at = round((xc + 0.5) / 2 - len(text) / 2)  # its state, centred under the server ...
    cv.text(h - 1, max(0, min(at, cols - len(text))), text, col)  # ... unless that runs off the edge
