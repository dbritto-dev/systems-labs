"""The **cluster** view: server nodes on a grid, messages flying between them, and partitions.

Each node is one character, coloured by how far behind it is. Messages are dots moving from
one node to another at their real speed (~100 ms). A message dropped by a partition stops
half way and fades out in red. During a partition a red dashed line cuts the grid between
the groups that cannot talk. Clients sit in a column on the left and send their requests to
the nodes (white dots). A lab can put every node in one row (`columns`), e.g. a chain left to
right, and write a word under each node (`labels`), e.g. its role.

It draws a `ClusterFrame`; a `ClusterAdapter` per lab (live/adapters/<lab>.py) makes one.
"""

from __future__ import annotations

import math
from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BG, GREEN, RED, RGB, Canvas, mix
from live.views.base import Adapter, View, register

CLIENT: RGB = (139, 148, 158)


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

    def centre(i: int) -> tuple[float, float]:  # in dots
        if i < 0:  # the clients
            return 2 * 3 + 1, cv.h / 2
        r, c = cell(i)
        return c * 2 + 1, r * 4 + 2

    # The clients, on the left.
    for k in range(5):
        cv.text(cv.rows // 2 - 2 + k, 2, "○", CLIENT)
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
    # Messages that were dropped: red, half way, fading.
    for a, b, fade in fr.drops:
        (x0, y0), (x1, y1) = centre(a), centre(b)
        cv.blob((x0 + x1) / 2, (y0 + y1) / 2, mix(RED, BG, fade), 7, 1)
    # Messages in flight.
    for a, b, p, colour in fr.flights:
        (x0, y0), (x1, y1) = centre(a), centre(b)
        cv.dot(x0 + (x1 - x0) * p, y0 + (y1 - y0) * p, colour, 5)
    # The nodes on top.
    for i, colour in enumerate(fr.nodes):
        r, c = cell(i)
        cv.text(r, c, "◉", colour)
    for i, (word, colour) in enumerate(fr.labels or []):
        if i < n and word:
            r, c = cell(i)
            cv.text(r + 1, max(0, min(cv.cols - len(word), c - len(word) // 2)), word, colour)
    text, colour = fr.state
    cv.text(cv.rows - 1, max(0, (left + right) // 2 - len(text) // 2), text, colour)

