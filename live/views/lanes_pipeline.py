"""A variation of the **lanes** view: **pipeline**. The users and the door are the same; behind the door
stands a row of small servers, one after another (the stages of a pipeline, the services an event
passes through, the nodes of a chain), each with its own gauge filling from the bottom like a queue and
its name under it. Requests hop from box to box along the segments between them (or back, on a
lane of their own), and the ones that skip boxes fly over the top: straight up, straight across,
straight down.

    ○ ● ○ ○ ○        ┃     ┌───────────────────┐
    ○ ○ ○ ○ ○        ┃     ╷                   ╷
    ● ○ ○ ● ○ ·· • ··┃ ·•· ┌──┐ ··· ┌──┐ ·•· ┌──┐ ··· ┌──┐
    ○ ○ ● ○ ○        ┃ ··· │▓▓│ ·•· │  │ ··· │▓▓│ ··· │  │
    memory 54% · SINK SLOW  A 327    B 911    C 2.1k   sink

It draws a `PipelineFrame` (a LaneFrame plus the boxes and what moves between them); a
`PipelineAdapter` per lab makes one. The lanes view and its other variations are untouched.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

from live.canvas import BG, RED, RGB, Canvas, mix
from live.views.base import Adapter, View, register
from live.views.lanes import LaneFrame
from live.views.parts import (  # noqa: F401  (Leaf: part of this view's interface)
    Boxes, Caption, Door, Flights, Leaf, Outcomes, SegHops, Skip, Stage, UsersGrid, Wire, draw_parts,
)

DOOR_AT = 0.28  # the door, this far from the users grid to the right edge


@dataclass(slots=True)
class PipelineFrame(LaneFrame):
    """A LaneFrame (users, door, outcomes, the state under the users) plus the boxes behind the door.

    `hops` run along segment k, from box k - 1 (the door when k is 0) to box k (or back);
    `skips` fly on an arc over the top from box `src` (-1: the door) to box `dest`;
    `drops` are requests lost on a segment, fading in red there;
    the boxes after `gap_after` are out of the line: drawn after a gap, dimmed;
    with `two_way`, each segment is two lanes, one per direction; `over` keeps room above the boxes for
    the skips (a pipeline that never skips a box drops it, and its boxes stand taller)."""

    boxes: list[Leaf] = field(default_factory=list)
    hops: list[tuple[int, float, RGB, bool]] = field(default_factory=list)  # (segment, 0..1, colour, back)
    skips: list[tuple[int, int, float, RGB]] = field(default_factory=list)  # (src, dest, 0..1, colour)
    drops: list[tuple[int, float]] = field(default_factory=list)  # (segment, 0..1 faded)
    gap_after: int | None = None
    two_way: bool = False
    over: bool = True


class PipelineAdapter(Adapter):
    """Feeds the pipeline view for one lab."""

    @abstractmethod
    def frame(self, variant: str, t: float, users: int) -> PipelineFrame:
        """The picture at t, for a grid of `users` circles (as for the lanes view)."""


@register
class PipelineView(View):
    name = "pipeline"

    def draw(self, cv: Canvas, adapter: Adapter, variant: str, t: float) -> None:
        assert isinstance(adapter, PipelineAdapter)
        draw_pipeline(cv, lambda n: adapter.frame(variant, t, n))


def draw_pipeline(cv: Canvas, make) -> None:
    st = Stage.on(cv)
    fr = make(st.n)
    xg = st.gx + (cv.cols * 2 - st.gx) * DOOR_AT  # the door
    text, colour = fr.state
    state = Caption(text, colour, st.gx / 2)  # under the users grid (from the left edge when it is long)
    free = max(0, round((state.x + 0.5) / 2 - len(text) / 2)) + len(text) + 1  # the last row, after it
    boxes = Boxes(fr.boxes, xg, cv.cols * 2 - 2, fr.gap_after, free, fr.two_way, fr.over)
    drops = [(k, 0.5, mix(RED, BG, fade), False) for k, fade in fr.drops]
    draw_parts(st, [
        UsersGrid(fr.users),
        Wire(st.gx + 2, xg - 2),  # users → door
        Door(xg, fr.closed, fr.door_color),
        Flights(fr.flights, xg),
        Outcomes(fr.outcomes, xg),
        boxes,  # the boxes, the segments between them and their names
        Skip(fr.skips, boxes),  # over the top
        SegHops(fr.hops + drops, boxes),  # box → box
        state,
    ])
