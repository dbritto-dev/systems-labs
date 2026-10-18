"""A variation of the **lanes** view: **peers**. The users and the door are the same (the door is the
clients' router, the network in front of the cluster); instead of one server, the peers stand on an
ellipse filling the rest of the picture (3 a triangle, 5 a pentagon, 8 an octagon), the first at the top
and the others clockwise. Each is a small box with its gauge and its outline colour (its role, or what the
others think of it), and its name on the row under it. Dotted lines are the links that matter right now
(the ones that carried messages a moment ago, and a few the lab always shows); a message flies along its
link, a lost one stops short of the middle and fades in red, and a partition puts a red ✕ on every link
between the groups.

    ○ ● ○ ○ ○     ┆             ┌───┐
    ● ○ ○ ● ○ ··•·┆·•·      ·· ·└───┘·· ·
    ○ ○ ● ○ ○     ┆   ┌───┐ n3 leader t4 ┌───┐
                  ┆   └───┘·· ·✕· ·· ·· └───┘
                  ┆   n1 cand t5        n4 t4
                            CONNECTED

It draws a `PeersFrame` (a LaneFrame plus the peers and what passes between them); a `PeersAdapter` per lab
makes one. The other lanes views are untouched.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import RGB, Canvas
from live.views.base import Adapter, View, register
from live.views.lanes import LaneFrame
from live.views.parts import (  # noqa: F401  (Leaf and LINE: part of this view's interface)
    LINE, Caption, Door, Flights, Leaf, Links, Outcomes, PeerHops, PeerRing, Stage, UsersGrid, Wire, draw_parts,
)


@dataclass(slots=True)
class PeersFrame(LaneFrame):
    """A LaneFrame (users, door, outcomes, the state, under the ring) plus the peers. Here `flights` are the
    messages between peers (src, dest, 0..1, colour; -1 is the door), and the users' requests on their way
    to the door are `requests` (what `flights` holds in the lanes view)."""

    flights: list[tuple[int, int, float, RGB]] = field(default_factory=list)  # type: ignore[assignment]
    requests: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (user, 0..1, colour, big)
    peers: list[Leaf] = field(default_factory=list)
    links: list[tuple[int, int, RGB]] = field(default_factory=list)  # only the links to draw (LINE: plain)
    # A word on a link, when it fits; or (words, colour): the first of the words that fits, longest first.
    link_labels: dict[tuple[int, int], str | tuple[tuple[str, ...], RGB]] = field(default_factory=dict)
    groups: list[int] | None = None  # a partition: the group of each peer; links between groups are cut
    drops: list[tuple[int, int, float]] = field(default_factory=list)  # (src, dest, 0..1 faded): lost
    two_way: bool = False  # each link as two lanes, one per direction, so messages each way never mix
    column: bool = False  # the peers in one column, every line straight (else on a ring)


class PeersAdapter(Adapter):
    """Feeds the peers view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        """The picture at t, for a grid of `users` circles (as for the lanes view)."""


@register
class PeersView(View):
    name = "peers"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, PeersAdapter)
        draw_peers(cv, lambda n: adapter.frame(variant, t, n))


def door_x(st: Stage) -> float:
    """The door: just right of the users grid."""
    return st.gx + 8


def draw_peers(cv: Canvas, make) -> None:
    st = Stage.on(cv)
    fr = make(st.n)
    xg = door_x(st)
    ring = PeerRing(fr.peers, int(xg // 2) + 3, column=fr.column, door=xg)
    ring.place(st)
    draw_parts(st, [
        UsersGrid(fr.users),
        Wire(st.gx + 2, xg - 2),  # users → the door
        Door(xg, fr.closed, fr.door_color),
        Flights(fr.requests, xg),
        Outcomes(fr.outcomes, xg),
        Links(fr.links, ring, fr.groups, fr.drops, fr.link_labels, fr.two_way),
        ring,
        PeerHops(fr.flights, ring, xg, fr.two_way),  # peer ⇄ peer, and the door → a peer
        Caption(*fr.state, ring.centre),  # the state, under the ring
    ])
