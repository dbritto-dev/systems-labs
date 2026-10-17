"""The parts the lanes family of pictures is built from (the Component pattern).

A picture is a list of parts drawn in order on one `Stage` (the canvas and the geometry they share: the
users grid on the left, the middle line, the body rows). The lanes view, and its variations relay and
fan-out, are just different lists:

    lanes   UsersGrid, Wire, Door, Flights, Outcomes, Server, Caption
    relay   UsersGrid, Wire×3, Door, Flights, Outcomes, Hops, Server×2, Caption×2
    fan-out UsersGrid, Wire×2, Door, Flights, Outcomes, Leaves, FanHops, Server, Caption×2
    pipeline UsersGrid, Wire, Door, Flights, Outcomes, Boxes, Skip, SegHops, Caption

A new variation is a new list (and, rarely, a new part), not another copy of the drawing code.
Positions are in Braille dots (2 per column, 4 per row) unless a name says rows or cols.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from live.canvas import BG, BLUE, DIM, RED, RGB, WHITE, Canvas, mix

GRID_COLS = 5  # users per row in the grid
IDLE: RGB = (52, 58, 70)  # a user with nothing in flight
LINE: RGB = (46, 52, 64)  # the dotted lines requests travel along
OUTLINE: RGB = (130, 140, 155)  # a server's case
LABEL_COLS = 10  # room for a small server's name, right of it
LANE = 3  # dots between a link's middle and each of its two lanes, when it has two


TRAIL = (0.035, 0.07)  # how far behind (in 0..1 of the way) the two dots of a moving dot's trail sit
TRAIL_FADE = (0.55, 0.78)  # and how faded they are


def ease(k: float) -> float:
    """Where a dot is drawn for 0..1 of its way: it eases out as it arrives (half linear, half a quadratic
    ease-out), so a dot slows a little before it lands instead of stopping dead. 0 and 1 stay put."""
    k = max(0.0, min(1.0, k))
    return 0.5 * k + 0.5 * (1 - (1 - k) ** 2)


def moving_dot(cv: Canvas, at, k: float, col: RGB, radius: int) -> None:
    """A dot on its way (`at(k)` gives its (x, y) for 0..1), eased, with a short fading trail behind it."""
    for lag, fade in zip(TRAIL, TRAIL_FADE):
        if k - lag > 0:
            x, y = at(ease(k - lag))
            cv.blob(x, y, mix(col, BG, fade), 3, 1)
    x, y = at(ease(k))
    cv.blob(x, y, col, 6, radius)


@dataclass(slots=True)
class Stage:
    """The canvas and the geometry every part of a lanes-family picture shares."""

    cv: Canvas
    body0: int  # the first and last rows of the picture (the row under it is for captions)
    body1: int
    n: int  # users in the grid
    ymid: float  # the middle line, in dots
    gx: float  # the users grid's right edge, in dots

    @classmethod
    def on(cls, cv: Canvas) -> "Stage":
        body0, body1 = 0, cv.rows - 2
        gr = max(3, body1 - body0 + 1)
        return cls(cv, body0, body1, GRID_COLS * gr, (body0 + (body1 - body0 + 1) / 2) * 4, (1 + GRID_COLS * 2) * 2)

    @property
    def server_x(self) -> float:
        """Where the lanes view puts its server's centre; the variations keep the right server there too."""
        return (self.cv.cols - 7) * 2 + 1

    @property
    def top(self) -> int:  # the body's top and bottom, in dots, for parts as tall as the picture
        return self.body0 * 4 + 2

    @property
    def bottom(self) -> int:
        return self.body1 * 4 + 2


@dataclass(slots=True)
class UsersGrid:
    """The users: ○ idle, ● waiting, coloured by how much extra work they cost."""

    users: dict[int, tuple[RGB, bool]]

    def draw(self, st: Stage) -> None:
        for i in range(st.n):
            r, c = st.body0 + i // GRID_COLS, 1 + (i % GRID_COLS) * 2
            col, busy = self.users.get(i, (IDLE, False))
            st.cv.text(r, c, "●" if busy else "○", col)


@dataclass(slots=True)
class Wire:
    """A dotted line along the middle, from x0 to x1."""

    x0: float
    x1: float

    def draw(self, st: Stage) -> None:
        for x in range(int(self.x0), int(self.x1), 3):
            st.cv.dot(x, st.ymid, LINE, 0)


@dataclass(slots=True)
class Door:
    """Whatever stands in front of the server: a solid bar when closed, dotted when open."""

    x: float
    closed: bool = False
    colour: RGB | None = None  # default: red when closed, dim when open

    def draw(self, st: Stage) -> None:
        if self.closed:
            for dx in (0, 1):
                st.cv.line([(self.x + dx, st.body0 * 4), (self.x + dx, st.body1 * 4 + 3)], self.colour or RED, 2)
        else:
            for y in range(int(st.body0 * 4), int(st.body1 * 4 + 4), 3):
                st.cv.dot(self.x, y, self.colour or DIM, 1)


@dataclass(slots=True)
class Flights:
    """Requests in flight: leave a user, join the line, reach the door (0..1 of the way)."""

    flights: list[tuple[int, float, RGB, bool]]  # (user, 0..1, colour, big)
    door: float

    def draw(self, st: Stage) -> None:
        for i, k, col, big in self.flights:
            y0 = (st.body0 + i // GRID_COLS) * 4 + 2

            def at(e: float, y0: float = y0) -> tuple[float, float]:
                return st.gx + (self.door - 3 - st.gx) * e, y0 + (st.ymid - y0) * min(1.0, e / 0.2)

            moving_dot(st.cv, at, k, col, 2 if big else 1)


@dataclass(slots=True)
class Outcomes:
    """What happened at the door, fading (at most 8)."""

    outcomes: list[tuple[RGB, float]]  # (colour, 0..1 faded)
    door: float

    def draw(self, st: Stage) -> None:
        for j, (col, age) in enumerate(self.outcomes[:8]):
            st.cv.blob(self.door - 4, st.ymid + (j - 3.5) * 3, mix(col, BG, age), 6, 1)


@dataclass(slots=True)
class Hops:
    """Requests passed on along the middle line, from x0 to x1 (0..1 of the way)."""

    hops: list[tuple[float, RGB, bool]]  # (0..1, colour, big)
    x0: float
    x1: float

    def draw(self, st: Stage) -> None:
        for k, col, big in self.hops:
            moving_dot(st.cv, lambda e: (self.x0 + (self.x1 - self.x0) * e, st.ymid), k, col, 2 if big else 1)


def draw_server(cv: Canvas, xc: float, y0: float, y1: float, rgb: RGB, fill: float, fill_rgb: RGB) -> None:
    """A server: a rectangle with three drive bays and a status light at the top, and a gauge inside that
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


@dataclass(slots=True)
class Server:
    """A server as tall as the picture, centred at x."""

    x: float
    outline: RGB = OUTLINE
    fill: float = 0.0
    gauge: RGB = BLUE

    def draw(self, st: Stage) -> None:
        draw_server(st.cv, self.x, st.top, st.bottom, self.outline, self.fill, self.gauge)


@dataclass(slots=True)
class Caption:
    """A word on the row under the picture, centred under x (but never off the edge)."""

    text: str
    colour: RGB
    x: float

    def draw(self, st: Stage) -> None:
        at = round((self.x + 0.5) / 2 - len(self.text) / 2)
        st.cv.text(st.cv.rows - 1, max(0, min(at, st.cv.cols - len(self.text))), self.text, self.colour)


# ---------------------------------------------------------------- fan-out: small servers, stacked on the right


@dataclass(slots=True)
class Leaf:
    """One of the small servers on the right."""

    label: tuple[str, RGB] = ("", WHITE)  # its name, right of it (or a word about it: "#1 hangs")
    fill: float = 0.0  # its gauge, 0..1, filling from the left
    gauge: RGB = BLUE
    outline: RGB = OUTLINE
    short: str = ""  # the name written top to bottom, when given (instead of the full label) ...
    tiny: str = ""  # ... and a tinier one, for when the short one does not fit


def draw_leaf(cv: Canvas, x0: float, x1: float, y0: float, y1: float, leaf: Leaf) -> None:
    """A small server: a case, and a gauge that fills from the left."""
    y0, y1 = int(y0), int(y1)
    cv.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], leaf.outline, 2)
    right = x0 + 2 + (x1 - x0 - 4) * max(0.0, min(1.0, leaf.fill))
    for y in range(y0 + 2, y1 - 1, 2):
        for x in range(int(x0 + 2), int(right), 2):
            cv.dot(x + (y & 1), y, leaf.gauge, 1)


@dataclass(slots=True)
class Leaves:
    """The small servers stacked between x0 and x1, a dotted line from `sx` (on the middle line) to each, and
    their names: beside them, or top to bottom in capitals when `vertical`. The lines are slanted, or with
    `straight` level: each leaves `sx` at its own server's height and runs straight across to it (for a
    relay as tall as the column of servers)."""

    leaves: list[Leaf]
    x0: float
    x1: float
    sx: float
    vertical: bool = False
    label_cols: int = LABEL_COLS  # room for each name, right of its server (the view widens it when it can)
    straight: bool = False
    mids: list[float] = field(default_factory=list)  # filled when drawn: each one's middle, for FanHops
    ymid: float = 0.0  # filled when drawn: the middle line, where the lines leave `sx`

    def at(self, ym: float, e: float) -> tuple[float, float]:
        """The point e (0..1) of the way along the line to the server whose middle is ym."""
        y0 = ym if self.straight else self.ymid
        return self.sx + (self.x0 - 3 - self.sx) * e, y0 + (ym - y0) * e

    def boxes(self, st: Stage) -> list[tuple[float, float]]:
        """(top dot, bottom dot) of each small server."""
        k = max(1, len(self.leaves))
        top, bottom = st.body0 * 4 + 1, st.body1 * 4 + 3
        slot_h = (bottom - top) / k
        out = []
        for j in range(len(self.leaves)):
            y0 = top + j * slot_h + 1
            y1 = top + (j + 1) * slot_h - 4  # a gap between them
            out.append((y0, max(y1, y0 + 5)))  # never thinner than a gauge
        return out

    def draw(self, st: Stage) -> None:
        cv, h = st.cv, st.cv.rows
        boxes = self.boxes(st)
        rows = []  # the text rows each vertical name may take, a blank row between names
        for j, (y0, y1) in enumerate(boxes):
            r0 = max(int(y0 // 4), rows[-1][1] + 2 if rows else 0)
            r1 = min(h - 2, int(y1 // 4))
            if j + 1 < len(boxes) and int(boxes[j + 1][0] // 4) <= r1 + 1:
                r1 -= 1  # the next box starts on the very next row
            rows.append((r0, r1))
        # One form for all the names, so they match: the short one if it fits every box, else the tiny one.
        # (The full name is only for servers that have no short form.)
        forms = [[w.upper() for w in ((lf.short, lf.tiny) if lf.short else (lf.label[0], lf.tiny))]
                 for lf in self.leaves]
        pick = next((k for k in range(2)
                     if all(f[k] and len(f[k]) <= r1 - r0 + 1 for f, (r0, r1) in zip(forms, rows))), None)
        self.mids, self.ymid = [round((y0 + y1) / 2) for y0, y1 in boxes], st.ymid

        def dotted(x0: float, y0: float, x1: float, y1: float) -> None:
            steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / 3))
            for s in range(steps + 1):
                cv.dot(x0 + (x1 - x0) * s / steps, y0 + (y1 - y0) * s / steps, LINE, 0)

        for j, leaf in enumerate(self.leaves):
            y0, y1 = boxes[j]
            ym = self.mids[j]
            dotted(self.sx, ym if self.straight else st.ymid, self.x0 - 2, ym)
            draw_leaf(cv, self.x0, self.x1, y0, y1, leaf)
            text, col = leaf.label
            if self.vertical:  # one letter a row, in capitals, centred beside the server
                r0, r1 = rows[j]
                room = max(1, r1 - r0 + 1)
                if pick is not None:
                    word = forms[j][pick]
                else:  # nothing fits everywhere: the shortest form there is, cut
                    last = next((w for w in reversed(forms[j]) if w), "")
                    word = last if len(last) <= room else last[: max(0, room - 1)] + "…"
                top_row = r0 + (room - len(word)) // 2
                for k, ch in enumerate(word):
                    cv.text(top_row + k, self.x1 // 2 + 1, ch, col)
            else:
                if len(text) > self.label_cols - 1 and leaf.short:  # a small screen: the short name
                    text = leaf.short
                cv.text(min(h - 2, int(ym // 4)), self.x1 // 2 + 2, text[:self.label_cols - 1], col)


@dataclass(slots=True)
class FanHops:
    """Requests between the relay and a small server, along that server's line (or back)."""

    hops: list[tuple[int, float, RGB, bool]]  # (leaf, 0..1, colour, back)
    leaves: Leaves  # drawn first: it knows where each small server sits

    def draw(self, st: Stage) -> None:
        lv = self.leaves
        for j, p, col, back in self.hops:
            if 0 <= j < len(lv.mids):
                ym = lv.mids[j]
                if back:  # on its way back: the same easing and trail, from the small server to the relay
                    moving_dot(st.cv, lambda e, ym=ym: lv.at(ym, 1 - e), p, col, 1)
                else:
                    moving_dot(st.cv, lambda e, ym=ym: lv.at(ym, e), p, col, 1)


# ---------------------------------------------------------------- fan-in: the small servers all call one store
#
#     fan-in  UsersGrid, Wire, Door, Flights, Outcomes, Leaves, Names, FanHops, Joins, JoinHops, [Cross],
#             Server, Caption×2


@dataclass(slots=True)
class Names:
    """Each small server's name (or a word about it: "n1 reads off"), at column `col` on its middle row, as
    long as the caller fitted it (Leaves cuts its names at LABEL_COLS)."""

    leaves: Leaves  # drawn first
    names: list[tuple[str, RGB]]
    col: int

    def draw(self, st: Stage) -> None:
        for ym, (text, colour) in zip(self.leaves.mids, self.names):
            st.cv.text(min(st.cv.rows - 2, int(ym // 4)), self.col, text, colour)


@dataclass(slots=True)
class Joins:
    """A dotted line from each small server (from `starts[j]`, after its name, on its middle) to the store's
    left edge `x1`: slanted to the middle line, or with `straight` level, at the server's own height (for a
    store as tall as the column of servers)."""

    leaves: Leaves  # drawn first: it knows where each small server sits
    starts: list[float]  # where each one's line starts, in dots
    x1: float
    straight: bool = False

    def end(self, st: Stage, ym: float) -> float:
        """Where a server's line meets the store: at its own height, or on the middle line."""
        return ym if self.straight else st.ymid

    def draw(self, st: Stage) -> None:
        for ym, x0 in zip(self.leaves.mids, self.starts):
            y1 = self.end(st, ym)
            steps = max(1, int((self.x1 - x0) / 3))
            for s in range(steps + 1):
                p = s / steps
                st.cv.dot(x0 + (self.x1 - x0) * p, ym + (y1 - ym) * p, LINE, 0)


@dataclass(slots=True)
class JoinHops:
    """Requests between a small server and the store, along that server's join line (or back)."""

    hops: list[tuple[int, float, RGB, bool]]  # (leaf, 0..1, colour, back)
    joins: Joins  # drawn first

    def draw(self, st: Stage) -> None:
        mids, starts, x1 = self.joins.leaves.mids, self.joins.starts, self.joins.x1 - 2
        for j, p, col, back in self.hops:
            if 0 <= j < min(len(mids), len(starts)):
                p = 1 - p if back else p
                y1 = self.joins.end(st, mids[j])
                st.cv.blob(starts[j] + (x1 - starts[j]) * p, mids[j] + (y1 - mids[j]) * p, col, 6, 1)


@dataclass(slots=True)
class Cross:
    """Messages from one small server to another, on a vertical dotted line at x (just right of them)."""

    hops: list[tuple[int, int, float, RGB]]  # (from leaf, to leaf, 0..1, colour)
    leaves: Leaves  # drawn first
    x: float

    def draw(self, st: Stage) -> None:
        mids = self.leaves.mids
        if len(mids) < 2:
            return
        for y in range(int(mids[0]), int(mids[-1]) + 1, 3):
            st.cv.dot(self.x, y, LINE, 0)
        for i, j, p, col in self.hops:
            if 0 <= i < len(mids) and 0 <= j < len(mids):
                st.cv.blob(self.x, mids[i] + (mids[j] - mids[i]) * p, col, 6, 1)


# ---------------------------------------------------------------- pipeline: small servers in a row


def draw_box(cv: Canvas, xc: float, y0: float, y1: float, rgb: RGB, fill: float, fill_rgb: RGB, rx: float) -> None:
    """A small server `rx` dots either side of xc: a case (no drive bays) and a gauge that fills from the
    bottom, like a queue."""
    x0, x1 = xc - rx, xc + rx
    y0, y1 = int(y0), int(y1)
    cv.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], rgb, 2)
    inner = (y1 - 2) - (y0 + 2)
    top = (y1 - 2) - inner * max(0.0, min(1.0, fill))
    y = y1 - 2
    while y > top:
        for x in range(int(x0 + 2), int(x1 - 1), 2):
            cv.dot(x + (y & 1), y, fill_rgb, 1)
        y -= 2


GAP_SLOTS = 0.5  # the gap before the boxes that are out of the line, in slots


@dataclass(slots=True)
class Boxes:
    """Small servers in a row, from the door (x0) to x1: segment k runs from box k - 1 (the door when k
    is 0) to box k. Each box is a slot wide: a segment, then the box. The boxes after `gap_after` are
    out of the line: drawn after a gap, dimmed. Without `over`, nothing skips boxes and they stand taller.
    With `two_way`, each segment is two lanes, LANE dots either
    side of the middle: what goes right keeps to the upper one, what comes back to the lower, so the two
    never mix. Their names go on the two rows under the picture
    (the last one only from column `free_from`, after the state): the full label if it fits, else the
    short form, else the tiny one. A label with a line break ("n0\\nhead") is a name and a word about it,
    one under the other when both fit, else on one line."""

    boxes: list[Leaf]
    x0: float
    x1: float
    gap_after: int | None = None
    free_from: int = 0
    two_way: bool = False
    over: bool = True  # room above the boxes for the requests that skip some
    xs: list[float] = field(default_factory=list)  # each box's centre (set when made)
    rx: float = 0.0  # half a box's width

    def __post_init__(self) -> None:
        n = len(self.boxes)
        out = self.gap_after is not None and self.gap_after < n - 1
        slot = (self.x1 - self.x0) / max(1, n + (GAP_SLOTS if out else 0))
        w = max(4.0, min(12.0, slot * 0.5))  # half the slot: the segments between boxes are as long as a box
        self.rx = float(int(w / 2))  # whole dots, so both sides of every box look the same
        gap = [slot * GAP_SLOTS if out and j > self.gap_after else 0.0 for j in range(n)]
        self.xs = [float(round(self.x0 + slot * (j + 1) - w / 2 + gap[j])) for j in range(n)]  # a segment, then the box

    def dimmed(self, j: int) -> bool:
        return self.gap_after is not None and j > self.gap_after

    def seg(self, k: int) -> tuple[float, float]:
        """Where segment k starts and ends, in dots (the first and last dot a request is drawn at)."""
        left = self.x0 + 2 if k == 0 else self.xs[k - 1] + self.rx + 2
        return left, self.xs[k] - self.rx - 3

    def lane_y(self, st: Stage, back: bool) -> float:
        """The y of the lane a request takes along a segment."""
        return st.ymid + (LANE if back else -LANE) if self.two_way else st.ymid

    def x_of(self, j: int) -> float:
        """Box j's centre (-1: the door)."""
        return self.x0 if j < 0 else self.xs[j]

    @staticmethod
    def span(st: Stage, over: bool = True) -> tuple[int, int]:
        """A box's top and bottom, in dots: room above for the requests that skip boxes (when there are
        any), and a row below for the names."""
        return st.top + (16 if over else 4), st.bottom - 4

    def draw(self, st: Stage) -> None:
        cv = st.cv
        y0, y1 = Boxes.span(st, self.over)
        last = self.gap_after if self.gap_after is not None else len(self.boxes) - 1
        for k in range(min(last + 1, len(self.boxes))):  # the dotted line between the door and each box
            a, b = self.seg(k)
            for y in {self.lane_y(st, False), self.lane_y(st, True)}:
                for x in range(int(a), int(b) + 1, 3):
                    cv.dot(x, y, LINE, 0)
        for j, box in enumerate(self.boxes):
            outline, gauge = box.outline, box.gauge
            if self.dimmed(j):
                outline, gauge = mix(outline, BG, 0.45), mix(gauge, BG, 0.45)
            draw_box(cv, self.xs[j], y0, y1, outline, box.fill, gauge, self.rx)
        self._names(st)

    def _names(self, st: Stage) -> None:
        cv = st.cv
        rows = (cv.rows - 2, cv.rows - 1)
        lo = {rows[0]: int(self.x0 // 2) + 2, rows[1]: self.free_from}  # clear of the door, and of the state
        taken: dict[int, list[tuple[int, int]]] = {r: [] for r in rows}

        def place(row: int, word: str, c: int) -> int | None:
            at = max(lo[row], min(math.floor(mid - len(word) / 2 + 0.5), cv.cols - len(word)))
            if not word or at + len(word) > cv.cols or not at <= c < at + len(word) + 1:
                return None  # it does not fit, or it would not stand under its box
            if any(at < b + 1 and a < at + len(word) + 1 for a, b in taken[row]):
                return None  # it would touch a name already there
            return at

        for j, box in enumerate(self.boxes):
            text, col = box.label
            if self.dimmed(j):
                col = mix(col, BG, 0.3)
            c = int((self.xs[j] + 0.5) // 2)  # the column the box's centre is in
            mid = self.xs[j] / 2 + 0.25  # the box's middle, in columns (a dot sits a quarter into its column)
            if "\n" in text:  # a name and a word about it (its role): one under the other, when both fit
                top, sub = text.split("\n", 1)
                a0, a1 = place(rows[0], top, c), place(rows[1], sub, c)
                if a0 is not None and a1 is not None:
                    for row, word, at in ((rows[0], top, a0), (rows[1], sub, a1)):
                        taken[row].append((at, at + len(word)))
                        cv.text(row, at, word, col)
                    continue
                text = f"{top} {sub}"
            forms = list(dict.fromkeys(w for w in (text, box.short, box.tiny) if w))
            spot = next(((row, word, at) for word in forms for row in rows
                         if (at := place(row, word, c)) is not None), None)
            if spot is None and forms:  # nothing fits: the shortest form there is, cut to the room under it
                word, room = forms[-1], int(self.rx) + 2
                word = word if len(word) <= room else word[: room - 1] + "…"
                spot = (rows[0], word, max(0, min(c - len(word) // 2, cv.cols - len(word))))
            if spot is not None:
                row, word, at = spot
                taken[row].append((at, at + len(word)))
                cv.text(row, at, word, col)


@dataclass(slots=True)
class SegHops:
    """Requests along the segments between the boxes (0..1 of the way, or back)."""

    hops: list[tuple[int, float, RGB, bool]]  # (segment, 0..1, colour, back)
    boxes: Boxes

    def draw(self, st: Stage) -> None:
        for k, p, col, back in self.hops:
            if 0 <= k < len(self.boxes.xs):
                a, b = self.boxes.seg(k)
                p = 1 - p if back else p
                st.cv.blob(a + (b - a) * max(0.0, min(1.0, p)), self.boxes.lane_y(st, back), col, 6, 1)


@dataclass(slots=True)
class Skip:
    """Requests that skip boxes fly over them, on two straight lines on the band above the boxes, one per
    direction (rightward on the upper one, leftward on the lower), so the two never mix: straight up out of
    `from`, along its line, straight down into `to`. Its requests are dots along that way (0..1 from `from`
    to `to`; -1 is the door). Only the stretches some pair uses are drawn."""

    skips: list[tuple[int, int, float, RGB]]  # (from, to, 0..1, colour)
    boxes: Boxes

    def _leg(self, j: int, right: bool) -> float:
        """The x of box j's leg up to the line going right (or left): either side of its middle."""
        return self.boxes.x0 + 3 if j < 0 else self.boxes.x_of(j) + (-2 if right else 2)

    def _paths(self, st: Stage) -> dict[tuple[int, int], list[tuple[float, float]]]:
        """Each pair's way, as its four corners."""
        n = len(self.boxes.xs)
        base = Boxes.span(st, self.boxes.over)[0] - 2
        out = {}
        for a, b, _, _ in self.skips:
            if -1 <= a < n and -1 <= b < n and a != b and (a, b) not in out:
                right = self.boxes.x_of(b) > self.boxes.x_of(a)
                y = st.top + (3 if right else 8)
                xa, xb = self._leg(a, right), self._leg(b, right)
                out[(a, b)] = [(xa, base), (xa, y), (xb, y), (xb, base)]
        return out

    @staticmethod
    def at(path: list[tuple[float, float]], p: float) -> tuple[float, float]:
        """The point 0..1 of the way along a path of straight legs, by its length."""
        legs = list(zip(path, path[1:]))
        sizes = [abs(x1 - x0) + abs(y1 - y0) for (x0, y0), (x1, y1) in legs]
        d = sum(sizes) * max(0.0, min(1.0, p))
        for ((x0, y0), (x1, y1)), size in zip(legs, sizes):
            if d <= size:
                k = d / size if size else 1.0
                return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
            d -= size
        return path[-1]

    def draw(self, st: Stage) -> None:
        paths = self._paths(st)
        cv = st.cv
        lines: dict[float, list[float]] = {}  # each line's y: the xs of the legs on it
        for (xa, base), (_, y), _, (xb, _) in paths.values():
            lines.setdefault(y, []).extend((xa, xb))
            for x in (xa, xb):  # the legs, dotted on a grid of their own so shared ones stay one line
                for yy in range(int(y) + 3, int(base) + 1, 3):
                    cv.dot(x, yy, LINE, 0)
        for y, xs in lines.items():
            for x in range(int(min(xs)), int(max(xs)) + 1, 3):
                cv.dot(x, y, LINE, 0)
        for a, b, p, col in self.skips:
            if (a, b) in paths:
                cv.blob(*self.at(paths[(a, b)], p), col, 6, 1)


def draw_parts(st: Stage, parts: list) -> None:
    """Draw a picture: each part, in order (later parts on top)."""
    for part in parts:
        part.draw(st)


# ---------------------------------------------------------------- peers: nodes on a ring, the links between them

CUT = "✕"  # a cut mark on a link a partition severs
PEER_SIZES = ((7, 3), (5, 2))  # a peer's box, in (cols, rows), the biggest first; then a lone ◉


@dataclass(slots=True)
class Spot:
    """Where one peer sits: its centre (dots), its box (dots; None for a ◉), its cell and its name's row."""

    x: float
    y: float
    hw: float  # half its size, a little over, where the links stop (dots)
    hh: float
    box: tuple[int, int, int, int] | None  # (x0, x1, y0, y1)
    row: int  # the ◉'s row (or the box's top row)
    col: int  # the ◉'s column (or the box's left column)
    name: str  # its name in the form that fits, and where it goes
    name_row: int
    name_col: int

    def edge(self, x: float, y: float) -> tuple[float, float]:
        """The point on the way to (x, y) where a line from the centre leaves the box."""
        dx, dy = x - self.x, y - self.y
        k = min(self.hw / abs(dx) if dx else 1e9, self.hh / abs(dy) if dy else 1e9, 1.0)
        return self.x + dx * k, self.y + dy * k


def ring_spots(cols: int, rows: int, n: int, c0: int, names: list[tuple[str, ...]]) -> list[Spot]:
    """Lay n peers out on an ellipse between column c0 and the right edge, rows 0 .. rows-1 (each peer's name
    on the row under it): the first at the top, then clockwise. The biggest box and the longest name that
    leave every box and name clear of the others; else smaller boxes, shorter names, and at last a ◉."""
    if n == 0:
        return []
    import math

    unit = [(math.cos(-math.pi / 2 + 2 * math.pi * k / n), math.sin(-math.pi / 2 + 2 * math.pi * k / n))
            for k in range(n)]
    xs, ys = [u for u, _ in unit], [v for _, v in unit]

    def spread(v: float, lo: float, hi: float, a: float, b: float) -> int:
        return round((a + b) / 2 if hi - lo < 1e-9 else a + (v - lo) / (hi - lo) * (b - a))

    def overlap(p, q) -> bool:  # (row, c0, c1) cells, inclusive; a name keeps one blank column round it
        return p[0] == q[0] and p[1] <= q[2] and q[1] <= p[2]

    forms = range(max(len(f) for f in names))  # a box with its whole name, a smaller box, a shorter name ...
    tries = [(wc, hr, form) for form in forms for wc, hr in PEER_SIZES] + [(1, 1, form) for form in forms]
    best: list[Spot] = []
    for wc, hr, form in tries:
        spots, cells = [], []  # cells: per peer, the (row, c0, c1) its box and name take
        for k in range(n):
            r = spread(ys[k], min(ys), max(ys), 0, rows - 1 - hr)
            c = spread(xs[k], min(xs), max(xs), c0, cols - wc)
            words = names[k]
            word = words[min(form, len(words) - 1)] if words else ""
            centre = c + (wc - 1) / 2
            nc = max(c0, min(cols - len(word), round(centre - (len(word) - 1) / 2)))
            if wc == 1:
                x, y, box, hw, hh = c * 2 + 1, r * 4 + 2, None, 2.5, 3.0
            else:
                x0, x1, y0, y1 = c * 2, (c + wc) * 2 - 1, r * 4 + 1, (r + hr) * 4 - 1
                x, y, box, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x0, x1, y0, y1), (x1 - x0) / 2 + 2, (y1 - y0) / 2 + 2
            spots.append(Spot(x, y, hw, hh, box, r, c, word, r + hr, nc))
            mine = [(rr, c, c + wc - 1) for rr in range(r, r + hr)]
            if word:
                mine.append((r + hr, nc - 1, nc + len(word)))
            cells.append(mine)
        clear = all(not overlap(p, q) for i in range(n) for j in range(i + 1, n) for p in cells[i] for q in cells[j])
        if clear:
            return spots
        best = spots
    return best  # nothing fits: the smallest there is


@dataclass(slots=True)
class PeerRing:
    """The peers on an ellipse right of column `c0` (3 a triangle, 5 a pentagon, 8 an octagon), each a small
    box with its gauge (or a ◉ when cramped) and its name on the row under it. `spots` is filled by `place`
    (Links and PeerHops call it too: they need to know where each peer sits)."""

    peers: list[Leaf]
    c0: int
    spots: list[Spot] = field(default_factory=list)

    def place(self, st: Stage) -> list[Spot]:
        if not self.spots and self.peers:
            names = [tuple(w for w in (p.label[0], p.short, p.tiny) if w) or ("",) for p in self.peers]
            self.spots = ring_spots(st.cv.cols, st.body1 + 1, len(self.peers), self.c0, names)
        return self.spots

    def cells(self, st: Stage) -> set[tuple[int, int]]:
        """The (row, col) cells the boxes and the names take (a name with a blank column each side)."""
        out: set[tuple[int, int]] = set()
        for s in self.place(st):
            wc = 1 if s.box is None else (s.box[1] - s.box[0] + 1) // 2
            out |= {(r, c) for r in range(s.row, s.name_row) for c in range(s.col, s.col + wc)}
            if s.name:
                out |= {(s.name_row, c) for c in range(s.name_col - 1, s.name_col + len(s.name) + 1)}
        return out

    @property
    def centre(self) -> float:
        """The middle of the ring, across (dots): where the state goes under it."""
        if not self.spots:
            return 0.0
        return (min(s.x for s in self.spots) + max(s.x for s in self.spots)) / 2

    def draw(self, st: Stage) -> None:
        cv = st.cv
        for peer, s in zip(self.peers, self.place(st)):
            if s.box is None:
                cv.text(s.row, s.col, "◉", peer.outline)
            else:
                draw_leaf(cv, *s.box, peer)
            if s.name and s.name_row <= st.body1:
                cv.text(s.name_row, s.name_col, s.name, peer.label[1])



def lane(ends: tuple[tuple[float, float], tuple[float, float]], off: float):
    """The same segment moved `off` dots to the right of its direction (y grows down): with two lanes, what
    goes a → b keeps to its right, and what comes back to its own right, so the two never mix."""
    import math

    (x0, y0), (x1, y1) = ends
    n = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / n * off, (x1 - x0) / n * off
    return (x0 + nx, y0 + ny), (x1 + nx, y1 + ny)


@dataclass(slots=True)
class Links:
    """The links between peers: dotted lines from box edge to box edge, LINE-coloured unless the picture gives
    a colour; a red ✕ at the middle of a link between different `groups` (a partition cuts it); and the
    messages lost on a link, red, stopped short of its middle, fading. With `two_way`, each link is two
    lanes, one per direction (see `lane`), and a lost message stops on its own."""

    links: list[tuple[int, int, RGB]]
    ring: PeerRing
    groups: list[int] | None = None
    drops: list[tuple[int, int, float]] = field(default_factory=list)  # (src, dest, 0..1 faded)
    # A word at a link's middle, if it fits; or (words, colour): the first of the words that fits, longest first.
    labels: dict[tuple[int, int], str | tuple[tuple[str, ...], RGB]] = field(default_factory=dict)
    two_way: bool = False

    def ends(self, st: Stage, a: int, b: int) -> tuple[tuple[float, float], tuple[float, float]] | None:
        spots = self.ring.place(st)
        if not (0 <= a < len(spots) and 0 <= b < len(spots)) or a == b:
            return None
        sa, sb = spots[a], spots[b]
        return sa.edge(sb.x, sb.y), sb.edge(sa.x, sa.y)

    def draw(self, st: Stage) -> None:
        import math

        cv = st.cv
        for a, b, col in self.links:
            ends = self.ends(st, a, b)
            if ends is None:
                continue
            plain = col == LINE
            gap = 3 if plain else 2
            for (x0, y0), (x1, y1) in ((lane(ends, LANE), lane(ends, -LANE)) if self.two_way else (ends,)):
                steps = max(1, int(math.hypot(x1 - x0, y1 - y0) / gap))
                for s in range(steps + 1):
                    cv.dot(x0 + (x1 - x0) * s / steps, y0 + (y1 - y0) * s / steps, col, 0 if plain else 1)
        for a, b, fade in self.drops:
            ends = self.ends(st, a, b)
            if ends is not None and self.two_way:
                ends = lane(ends, LANE)
            if ends is not None:
                (x0, y0), (x1, y1) = ends
                cv.blob(x0 + (x1 - x0) * 0.4, y0 + (y1 - y0) * 0.4, mix(RED, BG, max(0.0, min(1.0, fade))), 7, 1)
        taken = self.ring.cells(st)
        if self.groups is not None:  # a cut mark at the middle of each link between groups, clear of the names
            g = self.groups
            for a, b, _ in self.links:
                ends = self.ends(st, a, b)
                if ends is None or a >= len(g) or b >= len(g) or g[a] == g[b]:
                    continue
                (x0, y0), (x1, y1) = ends
                for k in (0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74):
                    r, c = int(y0 + (y1 - y0) * k) // 4, int(x0 + (x1 - x0) * k) // 2
                    if (r, c) not in taken and 0 <= r <= st.body1 and 0 <= c < cv.cols:
                        cv.text(r, c, CUT, RED)
                        taken.add((r, c))
                        break
        for (a, b), label in self.labels.items():  # a word on a link, where it does not cover anything
            ends = self.ends(st, a, b)
            if ends is None:
                continue
            words, colour = ((label,), OUTLINE) if isinstance(label, str) else label
            (x0, y0), (x1, y1) = ends
            for word in filter(None, words):
                r, c = int((y0 + y1) / 2) // 4, round((x0 + x1) / 4 - len(word) / 2)
                cells = {(r, c + k) for k in range(-1, len(word) + 1)}
                if 0 <= r <= st.body1 and 0 <= c and c + len(word) <= cv.cols and not cells & taken:
                    cv.text(r, c, word, colour)
                    taken |= cells
                    break


@dataclass(slots=True)
class PeerHops:
    """Messages between peers, along their link (0..1 of the way), and requests from the door (peer -1)
    straight to a peer's box, or back."""

    hops: list[tuple[int, int, float, RGB]]  # (src, dest, 0..1, colour)
    ring: PeerRing
    door: float  # the door's x, in dots
    two_way: bool = False  # each on its direction's lane of the link (see Links)

    def draw(self, st: Stage) -> None:
        spots = self.ring.place(st)
        dx, dy = self.door + 2, st.ymid
        for a, b, p, col in self.hops:
            if a == b or not (-1 <= a < len(spots) and -1 <= b < len(spots)):
                continue
            if a == -1:
                (x0, y0), (x1, y1) = (dx, dy), spots[b].edge(dx, dy)
            elif b == -1:
                (x0, y0), (x1, y1) = spots[a].edge(dx, dy), (dx, dy)
            else:
                sa, sb = spots[a], spots[b]
                ends = sa.edge(sb.x, sb.y), sb.edge(sa.x, sa.y)
                (x0, y0), (x1, y1) = lane(ends, LANE) if self.two_way else ends
            p = max(0.0, min(1.0, p))
            st.cv.blob(x0 + (x1 - x0) * p, y0 + (y1 - y0) * p, col, 6, 1)
