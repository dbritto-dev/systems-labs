"""A variation of the **lanes** view: **fan-in**. The users and the door are the same, and so is the server
on the right (the one shared store: a database, a key-value service, the storage); in between stands a
column of small named nodes (cache servers, workers, the nodes of a cluster). A request flies from the door
to one node, and the node, when it has to, on to the store; answers can fly back. Nodes can also talk to
each other, on a vertical line just right of them.

    ○ ● ○ ○ ○      ·┌────┐ c0 ·····        ┌────────┐
    ● ○ ○ ● ○ ·· ┃··┌────┐ c1 ··•···· ·····│ ▬▬▬  ▪ │
    ○ ○ ● ○ ○      ·└────┘ c2 ·····        │▓▓▓▓    │
                 router                    OVERLOADED

It draws a `FaninFrame` (a LaneFrame, whose server is the store, plus the nodes and the requests on both
sides of them); a `FaninAdapter` per lab makes one. The other lanes views are untouched.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field, replace

from live.canvas import DIM, RGB, Canvas
from live.views.base import Adapter, View, register
from live.views.lanes import LaneFrame
from live.views.parts import (  # noqa: F401  (LABEL_COLS and Leaf: part of this view's interface)
    LABEL_COLS, Caption, Cross, Door, FanHops, Flights, JoinHops, Joins, Leaf, Leaves, Names, Outcomes, Server, Stage,
    UsersGrid, Wire, draw_parts,
)

LEAF_DOTS = 12  # the small servers' width, in dots
MIN_JOIN = 3  # columns a join line keeps at least, between a name and the store
NAME_COLS = 14  # the longest name or word beside a node ("n1 lost commit"), when there is room


@dataclass(slots=True)
class FaninFrame(LaneFrame):
    """A LaneFrame (users, door, outcomes; the store is its server, with its fill, gauge, outline and state)
    plus the column of small nodes. `hops` go between the door and a node, `joins` between a node and the
    store, `cross` from one node to another (drawn only when `peers`)."""

    leaves: list[Leaf] = field(default_factory=list)
    hops: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (leaf, 0..1, colour, back)
    joins: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (leaf, 0..1, colour, back)
    cross: list[tuple[int, int, float, RGB]] = field(default_factory=list)  # (from leaf, to leaf, 0..1, colour)
    peers: bool = False  # draw the node-to-node line
    door_label: tuple[str, RGB] = ("", DIM)  # a word under the door


class FaninAdapter(Adapter):
    """Feeds the fan-in view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float, users: int) -> FaninFrame:
        """The picture at t, for a grid of `users` circles (as for the lanes view)."""


@register
class FaninView(View):
    name = "fanin"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, FaninAdapter)
        draw_fanin(cv, lambda n: adapter.frame(variant, t, n))


def fit(leaf: Leaf, room: int) -> str:
    """The longest of a node's names (full, short, tiny) that fits `room` columns, else the shortest one, cut."""
    forms = [w for w in (leaf.label[0], leaf.short, leaf.tiny) if w]
    if not forms:
        return ""
    word = next((w for w in forms if len(w) <= room), None)
    if word is not None:
        return word
    last = min(forms, key=len)
    return last[:room]


def geometry(st: Stage, peers: bool = False) -> dict[str, float]:
    """Where everything stands, in dots (and the names' first column and room, in columns). With `peers`
    the names stand one column further right, past the node-to-node line."""
    xc = st.server_x  # the store, where every lanes picture has its server
    lx0 = int(round(st.gx + (xc - 8 - st.gx) * 0.45))  # the small nodes' left ...
    lx1 = lx0 + LEAF_DOTS  # ... and right edge
    xg = st.gx + (lx0 - st.gx) * 0.5  # the door
    col = lx1 // 2 + (3 if peers else 2)  # the names
    room = max(1, min(NAME_COLS, int(xc - 8) // 2 - MIN_JOIN - col))
    return dict(xc=xc, lx0=lx0, lx1=lx1, xg=xg, col=col, room=room, cross=(lx1 // 2 + 1) * 2, x1=xc - 10)


def draw_fanin(cv: Canvas, make) -> None:
    st = Stage.on(cv)
    fr = make(st.n)
    g = geometry(st, fr.peers)
    col, room = int(g["col"]), int(g["room"])
    names = [fit(lf, room) for lf in fr.leaves]
    boxes = [replace(lf, label=("", lf.label[1])) for lf in fr.leaves]  # the names are written by Names
    starts = [(col + len(w) + 1) * 2 if w else col * 2 for w in names]  # each join leaves after its name
    leaves = Leaves(boxes, g["lx0"], g["lx1"], g["xg"] + 2)
    joins = Joins(leaves, starts, g["x1"])
    parts = [
        UsersGrid(fr.users),
        Wire(st.gx + 2, g["xg"] - 2),  # users → door
        Door(g["xg"], fr.closed, fr.door_color),
        Flights(fr.flights, g["xg"]),
        Outcomes(fr.outcomes, g["xg"]),
        leaves,
        Names(leaves, [(w, lf.label[1]) for lf, w in zip(fr.leaves, names)], col),
        FanHops(fr.hops, leaves),  # door ⇄ a node
        joins,
        JoinHops(fr.joins, joins),  # a node ⇄ the store
    ]
    if fr.peers:
        parts.append(Cross(fr.cross, leaves, g["cross"]))  # node → node
    parts += [
        Server(g["xc"], fr.outline, fr.fill, fr.gauge),
        Caption(*fr.door_label, g["xg"]), Caption(*fr.state, g["xc"]),
    ]
    draw_parts(st, parts)
