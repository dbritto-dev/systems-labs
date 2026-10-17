"""The **cluster** view: server nodes on a grid, messages flying between them, and partitions.

Each node is one character, coloured by how far behind it is. Messages are dots moving from
one node to another at their real speed (~100 ms). A message dropped by a partition stops
half way and fades out in red. During a partition a red dashed line cuts the grid between
the groups that cannot talk. The clients sit on the left, one on each row of nodes, and their
requests go level along the row to the node (white dots), on a faint line. Every way has two
lanes, one per direction: what goes right keeps to the top of the row, what comes back to the
bottom, so the two never mix. A lab can put every node in one row (`columns`), e.g. a chain left to
right, and write a word under each node (`labels`), e.g. its role (a line break puts a second word
under the first: "n0\\nhead").

It draws a `ClusterFrame`; a `ClusterAdapter` per lab (live/adapters/<lab>.py) makes one.
"""

from __future__ import annotations

import math
from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BG, GREEN, RED, RGB, Canvas, mix
from live.views.parts import LINE, lane
from live.views.base import Adapter, View, register

CLIENT: RGB = (139, 148, 158)
SIDE = 1.5  # dots between the middle of a node's row and each of its two lanes


@dataclass(slots=True)
class ClusterFrame:
    """Everything the cluster view draws at one moment."""

    nodes: list[RGB] = field(default_factory=list)  # one colour per node, in grid order
    groups: list[int] | None = None  # during a partition: the group of each node
    flights: list[tuple[int, int, float, RGB]] = field(default_factory=list)  # (src, dest, 0..1, colour); -1 = clients
    drops: list[tuple[int, int, float]] = field(default_factory=list)  # (src, dest, 0..1 faded)
    state: tuple[str, RGB] = ("CONNECTED", GREEN)  # under the grid
    columns: int = 0  # nodes per row (0: a square grid); len(nodes) puts them all in one row, left to right
    labels: list[tuple[str, RGB]] | None = None  # a short word under each node, e.g. its role
    links: list[tuple[int, int]] = field(default_factory=list)  # who can talk to whom: faint dotted lines


class ClusterAdapter(Adapter):
    """Feeds the cluster view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float) -> ClusterFrame:
        """The picture at t."""


def grid_side(n: int) -> int:
    return max(1, math.ceil(math.sqrt(n)))


@register
class ClusterView(View):
    name = "cluster"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, ClusterAdapter)
        draw_cluster(cv, adapter.frame(variant, t))


def draw_cluster(cv: Canvas, fr: ClusterFrame) -> None:
    n = len(fr.nodes)
    if n == 0:
        return
    side = fr.columns or grid_side(n)
    rows = math.ceil(n / side)
    # The grid fills the canvas right of the clients column, leaving a row for the state.
    left, right = 8, cv.cols - 3
    top, bottom = 1, cv.rows - 3
    step_c = (right - left) / max(1, side - 1)
    step_r = (bottom - top) / max(1, rows - 1)

    def cell(i: int) -> tuple[int, int]:  # (row, col) of node i
        r, c = divmod(i, side)
        row = (top + bottom) / 2 if rows == 1 else top + r * step_r  # a lone row sits mid-height
        return round(row), round(left + c * step_c)

    def centre(i: int) -> tuple[float, float]:  # in dots: between the row's two lanes
        r, c = cell(i)
        return c * 2 + 1, r * 4 + 1.5

    client_x = 2 * 2 + 1  # the clients' column, in dots

    def ends(a: int, b: int) -> tuple[tuple[float, float], tuple[float, float]]:
        """The way from a to b (-1: the clients, on the row of the node they talk to: a level line), on
        the lane to the left of its direction: what goes right keeps to the top dots of the row and what
        comes back to the bottom ones, so the two never mix."""
        pa = (client_x, centre(b)[1]) if a < 0 else centre(a)
        pb = (client_x, centre(a)[1]) if b < 0 else centre(b)
        return lane((pa, pb), -SIDE)

    # The clients, on the left: one on each row of nodes, so their requests go level to the node.
    for r in sorted({cell(i)[0] for i in range(n)}):
        cv.text(r, 2, "○", CLIENT)
    # A partition: a dashed red cut between neighbouring nodes in different groups.
    if fr.groups is not None:
        for i in range(n):
            r, c = divmod(i, side)
            for j, vertical in ((i + 1, True), (i + side, False)):
                if j >= n or (vertical and c == side - 1) or fr.groups[i] == fr.groups[j]:
                    continue
                (x0, y0), (x1, y1) = centre(i), centre(j)
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                half = (step_r * 4 if vertical else step_c * 2) / 2
                for k in range(-int(half), int(half) + 1):
                    if k % 3 != 2:
                        if vertical:
                            cv.dot(mx, my + k, RED, 3)
                        elif (left - 1) * 2 <= mx + k <= (right + 1) * 2:  # keep off the clients
                            cv.dot(mx + k, my, RED, 3)

    def dotted(a: tuple[float, float], b: tuple[float, float]) -> None:
        (x0, y0), (x1, y1) = a, b
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / 3))
        for k in range(1, steps):
            cv.dot(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps, LINE, 0)

    # The links the nodes have (a topology), faint, under everything that moves.
    for a, b in fr.links:
        if 0 <= a < n and 0 <= b < n:
            dotted(centre(a), centre(b))
    # The clients' level lines, on the rows they talk to.
    talked = {(a, b) for a, b, *_ in fr.flights + fr.drops if (a < 0) != (b < 0) and max(a, b) < n}
    reach: dict[int, int] = {}  # a row: the furthest node on it the clients talk to
    for a, b in talked:
        i = max(a, b)
        r = cell(i)[0]
        reach[r] = max(reach.get(r, i), i, key=lambda j: cell(j)[1])
    for i in reach.values():
        for way in ((-1, i), (i, -1)):
            dotted(*ends(*way))
    # Messages that were dropped: red, half way, fading.
    ok = range(-1, n)
    for a, b, fade in fr.drops:
        if a in ok and b in ok and a != b:
            (x0, y0), (x1, y1) = ends(a, b)
            cv.blob((x0 + x1) / 2, (y0 + y1) / 2, mix(RED, BG, fade), 7, 1)
    # Messages in flight.
    for a, b, p, colour in fr.flights:
        if a in ok and b in ok and a != b:
            (x0, y0), (x1, y1) = ends(a, b)
            cv.dot(x0 + (x1 - x0) * p, y0 + (y1 - y0) * p, colour, 5)
    # The nodes on top.
    for i, colour in enumerate(fr.nodes):
        r, c = cell(i)
        cv.text(r, c, "◉", colour)
    for i, (text, colour) in enumerate(fr.labels or []):
        if i < n and text:
            r, c = cell(i)
            for k, word in enumerate(text.split("\n")):  # a line break: a name, and a word about it under it
                cv.text(r + 1 + k, max(0, min(cv.cols - len(word), c - len(word) // 2)), word, colour)
    text, colour = fr.state
    cv.text(cv.rows - 1, max(0, (left + right) // 2 - len(text) // 2), text, colour)
