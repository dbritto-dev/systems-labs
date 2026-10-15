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

from live.canvas import BLUE, DIM, RGB, Canvas
from live.views.base import Adapter, View, register
from live.views.lanes import LaneFrame
from live.views.parts import (
    OUTLINE, Caption, Door, Flights, Hops, Outcomes, Server, Stage, UsersGrid, Wire, draw_parts,
)


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
    st = Stage.on(cv)
    fr = make(st.n)
    xc = st.server_x  # the server's centre, where the lanes view has it
    xg = st.gx + (xc - 8 - st.gx) * 0.38  # the door
    xm = xg + (xc - 8 - xg) * 0.5  # the relay's centre
    rl = fr.relay
    draw_parts(st, [
        UsersGrid(fr.users),
        Wire(st.gx + 2, xg - 2), Wire(xg + 2, xm - 9), Wire(xm + 10, xc - 9),  # the two lines (the door between)
        Door(xg, fr.closed, fr.door_color),
        Flights(fr.flights, xg),  # users → door
        Outcomes(fr.outcomes, xg),
        Hops(fr.hops, xm + 10, xc - 11),  # relay → server
        Server(xm, rl.outline, rl.fill, rl.gauge),
        Server(xc, fr.outline, fr.fill, fr.gauge),
        Caption(*rl.label, xm), Caption(*fr.state, xc),  # a word under each server
    ])
