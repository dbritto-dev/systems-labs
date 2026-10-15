"""The **lanes** view: the users as a grid of circles on the left (○ idle, ● waiting, coloured by how much extra
work they cost), one dotted line with requests in flight to the door in front of the server (a gateway, a cache,
a queue), and the server as a rectangle with three drive bays and a gauge on the right. It draws a `LaneFrame`;
a `LaneAdapter` per lab (live/adapters/<lab>.py) makes one from that lab's World.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BLUE, GREEN, RGB, Canvas
from live.views.base import Adapter, View, register
from live.views.parts import (  # noqa: F401  (GRID_COLS, IDLE, LINE: shared with the variations and adapters)
    GRID_COLS, IDLE, LINE, OUTLINE, Caption, Door, Flights, Outcomes, Server, Stage, UsersGrid, Wire, draw_parts,
    draw_server as _server,
)


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


@register
class LanesView(View):
    name = "lanes"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, LaneAdapter)
        draw_lanes(cv, lambda n: adapter.frame(variant, t, n))


def draw_lanes(cv: Canvas, make) -> None:
    """Lay the picture out on the canvas; `make(users)` gives the LaneFrame for a grid of that many circles."""
    st = Stage.on(cv)
    lane = make(st.n)
    xc = st.server_x  # the server's centre, in dots
    xg = xc - 8 - 12  # the door, in dots
    draw_parts(st, [
        UsersGrid(lane.users),
        Wire(st.gx + 2, xg - 2),  # one dotted line from the users to the door
        Door(xg, lane.closed, lane.door_color),
        Flights(lane.flights, xg),
        Outcomes(lane.outcomes, xg),
        Server(xc, lane.outline, lane.fill, lane.gauge),
        Caption(*lane.state, xc),  # its state, centred under the server
    ])
