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

from live.canvas import Canvas
from live.views.base import Adapter, View, register
from live.views.lanes import LaneFrame
from live.views.lanes_relay import Relay
from live.views.parts import (  # noqa: F401  (LABEL_COLS and Leaf: part of this view's interface)
    LABEL_COLS, Caption, Door, FanHops, Flights, Leaf, Leaves, Outcomes, Server, Stage, UsersGrid, Wire, draw_parts,
)

@dataclass(slots=True)
class FanoutFrame(LaneFrame):
    """A LaneFrame (users, door, outcomes, state) plus the relay in the middle and the small servers on the
    right. `flights` go from the users to the door; `hops` from the relay to a server, or back."""

    relay: Relay = field(default_factory=Relay)
    leaves: list[Leaf] = field(default_factory=list)
    hops: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (leaf, 0..1, colour, back)
    vertical: bool = False  # write each name top to bottom in capitals, right of its server (the servers get wider)

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

def draw_fanout(cv: Canvas, make) -> None:
    st = Stage.on(cv)
    fr = make(st.n)
    lx1 = (cv.cols - (3 if fr.vertical else LABEL_COLS + 1)) * 2  # the small servers: their right edge ...
    lx0 = lx1 - (18 if fr.vertical else 12)  # ... and left edge (wider when the names stand beside them)
    xg = st.gx + (lx0 - st.gx) * 0.3  # the door
    xm = xg + (lx0 - 10 - xg) * 0.55  # the relay's centre
    rl = fr.relay
    leaves = Leaves(fr.leaves, lx0, lx1, xm + 10, fr.vertical)  # the lines leave the relay at xm + 10
    draw_parts(st, [
        UsersGrid(fr.users),
        Wire(st.gx + 2, xg - 2), Wire(xg + 2, xm - 9),  # users → door → relay
        Door(xg, fr.closed, fr.door_color),
        Flights(fr.flights, xg),
        Outcomes(fr.outcomes, xg),
        leaves,
        FanHops(fr.hops, leaves),  # relay ⇄ a small server
        Server(xm, rl.outline, rl.fill, rl.gauge),
        Caption(*rl.label, xm), Caption(*fr.state, (lx0 + lx1) / 2),
    ])
