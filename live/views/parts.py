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
    lines: int = 1  # in a column: the rows its words take under the box (a word about it on the second)

    def edge(self, x: float, y: float) -> tuple[float, float]:
        """The point on the way to (x, y) where a line from the centre leaves the box."""
        dx, dy = x - self.x, y - self.y
        k = min(self.hw / abs(dx) if dx else 1e9, self.hh / abs(dy) if dy else 1e9, 1.0)
        return self.x + dx * k, self.y + dy * k


def ring_spots(cols: int, rows: int, n: int, c0: int, names: list[tuple[str, ...]]) -> list[Spot]:
    """Lay n peers out on an ellipse between column c0 and the right edge, rows 0 .. rows-1 (each peer's name
    centred on the row under it, and a word about it centred under that: "n3" / "leader t4"): the first at
    the top, then clockwise. The biggest box and the longest name that leave every box and name clear of the
    others; else smaller boxes, shorter names, and at last a ◉. A box is as even or odd as the first name is
    long, so the name stands exactly in its middle."""
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
    first = names[0][0].split("\n")[0] if names and names[0] else ""
    sizes = [(wc + (wc - len(first)) % 2, hr) for wc, hr in PEER_SIZES]
    # A row for the words under the name when there is room; else they share the name's row ("n3 t4").
    tries = [(wc, hr, form, nr) for nr in (NAME_ROWS, 1) for form in forms for wc, hr in sizes]
    tries += [(1, 1, form, 1) for form in forms]
    best: list[Spot] = []
    for wc, hr, form, nr in tries:
        spots, cells = [], []  # cells: per peer, the (row, c0, c1) its box and name take
        for k in range(n):
            r = spread(ys[k], min(ys), max(ys), 0, rows - nr - hr)
            c = spread(xs[k], min(xs), max(xs), c0, cols - wc)
            words = names[k]
            word = words[min(form, len(words) - 1)] if words else ""
            lines = word.split("\n")[:nr] if nr > 1 else [word.replace("\n", " ")]
            nc = max(c0, min(cols - len(lines[0]), centred(c + wc / 2, word.split("\n")[0])))
            mid = nc + len(lines[0]) / 2
            if wc == 1:
                x, y, box, hw, hh = c * 2 + 1, r * 4 + 2, None, 2.5, 3.0
            else:
                x0, x1, y0, y1 = c * 2, (c + wc) * 2 - 1, r * 4 + 1, (r + hr) * 4 - 1
                x, y, box, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x0, x1, y0, y1), (x1 - x0) / 2 + 2, (y1 - y0) / 2 + 2
            spots.append(Spot(x, y, hw, hh, box, r, c, word, r + hr, nc, nr))
            mine = [(rr, c, c + wc - 1) for rr in range(r, r + hr)]
            for k2, line in enumerate(lines if word else []):
                at = nc if k2 == 0 else max(c0, min(cols - len(line), centred(mid, line)))
                mine.append((r + hr + k2, at - 1, at + len(line)))
            cells.append(mine)
        clear = all(not overlap(p, q) for i in range(n) for j in range(i + 1, n) for p in cells[i] for q in cells[j])
        if clear:
            return spots
        best = spots
    return best  # nothing fits: the smallest there is


NAME_ROWS = 2  # in a column: a peer's name under its box, and a word about it under that ("n2" / "cut off")
# In a column, the boxes and word rows tried, best first: a word under the name, else on its row, before
# the boxes shrink to a line. Each width is made even or odd like the names (see column_spots).
COLUMN_FORMS = ((7, 3, 2), (5, 2, 2), (7, 3, 1), (5, 2, 1), (3, 1, 2), (3, 1, 1))
WORD_ROOM = 7  # in a column, when a peer's word shares its name's row: the columns kept for it right of the box


def centred(mid: float, word: str) -> int:
    """The column a word starts at to stand centred on `mid` (in columns); when it cannot be exactly centred
    (an even word under an odd box), half a column to the left rather than to the right."""
    import math

    return math.floor(mid - len(word) / 2)


def column_spots(cols: int, rows: int, n: int, c0: int, names: list[tuple[str, ...]]) -> list[Spot]:
    """Lay n peers out in one column, top to bottom, in the middle of [c0, cols): the biggest box
    that leaves room under each for its name and a word about it (on the row under the name when there is
    room, else on the name's row; centred under the box), and a row more for the straight line down to the
    next one."""
    if n == 0:
        return []
    for wc, hr, lines in COLUMN_FORMS:
        if n * (hr + lines) + (n - 1) <= rows:
            break
    # A name stands exactly centred only under a box as even or odd as it is wide ("n0" under 8, "n10" under 7):
    # the boxes take the parity of the first name, one column wider when it differs.
    first = names[0][0].split("\n")[0] if names and names[0] else ""
    wc += (wc - len(first)) % 2
    gap = (rows - n * (hr + lines)) / max(1, n - 1) if n > 1 else 0
    c = round(c0 + (cols - c0) / 2 - wc / 2)
    spots = []
    for k in range(n):
        r = round(k * (hr + lines + gap)) if n > 1 else (rows - hr - lines) // 2
        x0, x1, y0, y1 = c * 2, (c + wc) * 2 - 1, r * 4 + 1, (r + hr) * 4 - 1
        word = names[k][0] if names[k] else ""
        x = (x0 + x1) / 2
        spots.append(Spot(x, (y0 + y1) / 2, (x1 - x0) / 2 + 2, (y1 - y0) / 2 + 2, (x0, x1, y0, y1),
                          r, c, word, r + hr, centred(x / 2 + 0.25, word.split("\n")[0]), lines))
    return spots


def along(path: list[tuple[float, float]], k: float) -> tuple[float, float]:
    """The point k (0..1) of the way along a path of straight legs, by length."""
    import math

    sizes = [math.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(path, path[1:])]
    d = sum(sizes) * max(0.0, min(1.0, k))
    for ((x0, y0), (x1, y1)), size in zip(zip(path, path[1:]), sizes):
        if d <= size:
            f = d / size if size else 1.0
            return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
        d -= size
    return path[-1]


def dotted_path(cv: Canvas, path: list[tuple[float, float]], col: RGB, gap: float, prio: int) -> None:
    """A path of straight legs, dotted every `gap` dots."""
    import math

    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        steps = max(1, int(math.hypot(x1 - x0, y1 - y0) / gap))
        for s_ in range(steps + 1):
            cv.dot(x0 + (x1 - x0) * s_ / steps, y0 + (y1 - y0) * s_ / steps, col, prio)


@dataclass(slots=True)
class PeerRing:
    """The peers on an ellipse right of column `c0` (3 a triangle, 5 a pentagon, 8 an octagon), each a small
    box with its gauge (or a ◉ when cramped) and its name on the row under it. With `column`, they stand in
    one column instead, and every line is straight: a level line from the door (at `door`) to each box,
    a vertical line between neighbours, and a bracket right of the column between the others. `spots` is
    filled by `place` (Links and PeerHops call it too: they need to know where each peer sits)."""

    peers: list[Leaf]
    c0: int
    spots: list[Spot] = field(default_factory=list)
    column: bool = False
    door: float = 0.0

    def place(self, st: Stage) -> list[Spot]:
        if not self.spots and self.peers:
            names = [tuple(w for w in (p.label[0], p.short, p.tiny) if w) or ("",) for p in self.peers]
            if self.column:  # a blank row above the state, so it never reads as a node's words; unless the
                # boxes would shrink to a line for it: then the row goes to the boxes
                spots = column_spots(st.cv.cols, st.body1, len(self.peers), self.c0, names)
                if spots and spots[0].box and (spots[0].box[3] + 1) // 4 - spots[0].row < 2:
                    spots = column_spots(st.cv.cols, st.body1 + 1, len(self.peers), self.c0, names)
                self.spots = spots
            else:
                self.spots = ring_spots(st.cv.cols, st.body1 + 1, len(self.peers), self.c0, names)
        return self.spots

    def path(self, st: Stage, a: int, b: int) -> list[tuple[float, float]] | None:
        """The way from peer a to peer b (-1: the door), as straight legs from edge to edge."""
        spots = self.place(st)
        if not (-1 <= a < len(spots) and -1 <= b < len(spots)) or a == b:
            return None
        if a == -1 or b == -1:  # the door: level to the box in a column, else from the middle of the door
            sp = spots[b if a == -1 else a]
            d = (self.door + 2, sp.y if self.column else st.ymid)
            way = [d, (sp.x - sp.hw, sp.y) if self.column else sp.edge(*d)]
            return way if a == -1 else way[::-1]
        sa, sb = spots[a], spots[b]
        if not self.column:
            return [sa.edge(sb.x, sb.y), sb.edge(sa.x, sa.y)]
        if abs(a - b) == 1:  # neighbours: straight down the column, from under the upper one's words
            up, low = (sa, sb) if sb.y > sa.y else (sb, sa)
            way = [(up.x, (up.name_row + up.lines) * 4 + 1), (low.x, low.y - low.hh)]
            return way if up is sa else way[::-1]
        x = self.bracket_x(st)  # the others: out to the right, along, and back in
        return [(sa.x + sa.hw, sa.y), (x, sa.y), (x, sb.y), (sb.x + sb.hw, sb.y)]

    def placed(self, s: Spot) -> list[tuple[int, int, str]]:
        """A peer's words, as (row, column, word): the name centred under its box, and every word after it
        centred on the name (so all of them share one middle, however the rounding falls)."""
        words = self.words(s)
        if not words:
            return []
        name = s.name.split("\n")[0]
        at = s.name_col  # the name, centred under its box (and kept on screen) when the peers were laid out
        mid = at + len(name) / 2
        out = [(s.name_row, at, words[0])]  # on one row, the word follows the name
        out += [(s.name_row + k, max(0, centred(mid, w)), w) for k, w in enumerate(words[1:], 1)]
        return out

    def words(self, s: Spot) -> list[str]:
        """A peer's words, a row each: its name, then a word about it (on one row when only one fits)."""
        if not s.name:
            return []
        parts = s.name.split("\n")
        return parts[:s.lines] if s.lines > 1 else [" ".join(parts)]

    def bracket_x(self, st: Stage) -> float:
        """Where the brackets between peers that are not neighbours run: a fixed way right of the boxes (further
        when a word shares its name's row), so they never move when a word appears."""
        s = self.place(st)[0]
        room = WORD_ROOM if s.lines == 1 else 2  # columns
        return min(s.x + s.hw + room * 2, st.cv.cols * 2 - 2)

    def cells(self, st: Stage) -> set[tuple[int, int]]:
        """The (row, col) cells the boxes and the names take (a name with a blank column each side)."""
        out: set[tuple[int, int]] = set()
        for s in self.place(st):
            wc = 1 if s.box is None else (s.box[1] - s.box[0] + 1) // 2
            hr = 1 if s.box is None else (s.box[3] + 1) // 4 - s.row
            out |= {(r, c) for r in range(s.row, s.row + hr) for c in range(s.col, s.col + wc)}
            for r, c0, word in self.placed(s):
                out |= {(r, c) for c in range(c0 - 1, c0 + len(word) + 1)}
        return out

    @property
    def centre(self) -> float:
        """The middle of the ring, across (dots): where the state goes under it."""
        if not self.spots:
            return 0.0
        return (min(s.x for s in self.spots) + max(s.x for s in self.spots)) / 2

    def draw(self, st: Stage) -> None:
        cv = st.cv
        if self.column:  # the level lines from the door, under the boxes
            for k in range(len(self.peers)):
                dotted_path(cv, self.path(st, -1, k) or [], LINE, 3, 0)
        for peer, s in zip(self.peers, self.place(st)):
            if s.box is None:
                cv.text(s.row, s.col, "◉", peer.outline)
            else:
                draw_leaf(cv, *s.box, peer)
            if not s.name:
                continue
            for k, (r, c, word) in enumerate(self.placed(s)):  # the name, then a word about it
                if r > st.body1:
                    continue
                c = max(0, min(c, cv.cols - len(word)))  # kept on screen, like the name
                if k == 0 and s.lines == 1 and "\n" in s.name:  # one row: the name, then its word beside it
                    name = s.name.split("\n", 1)[0]
                    cv.text(r, c, name, peer.outline)
                    cv.text(r, c + len(name) + 1, word[len(name) + 1:], peer.label[1])
                else:
                    cv.text(r, c, word, peer.label[1] if k else peer.outline)  # the name in the node's colour



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

    def path(self, st: Stage, a: int, b: int, back: bool = False) -> list[tuple[float, float]] | None:
        """Link a-b's way (its lane for a → b, with two lanes), as straight legs."""
        if not (0 <= a and 0 <= b):
            return None
        way = self.ring.path(st, a, b)
        if way is None or not self.two_way or len(way) != 2:
            return way
        return list(lane((way[0], way[1]), -LANE if back else LANE))

    def draw(self, st: Stage) -> None:
        cv = st.cv
        for a, b, col in self.links:
            way = self.ring.path(st, a, b)
            if way is None:
                continue
            plain = col == LINE
            ways = [self.path(st, a, b), self.path(st, a, b, back=True)] if self.two_way and len(way) == 2 else [way]
            for w in ways:
                dotted_path(cv, w, col, 3 if plain else 2, 0 if plain else 1)
        for a, b, fade in self.drops:
            way = self.path(st, a, b)
            if way is not None:
                cv.blob(*along(way, 0.4), mix(RED, BG, max(0.0, min(1.0, fade))), 7, 1)
        taken = self.ring.cells(st)
        if self.groups is not None:  # a cut mark at the middle of each link between groups, clear of the names
            g = self.groups
            for a, b, _ in self.links:
                way = self.ring.path(st, a, b)
                if way is None or a >= len(g) or b >= len(g) or g[a] == g[b]:
                    continue
                for k in (0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74):
                    x, y = along(way, k)
                    r, c = int(y) // 4, int(x) // 2
                    if (r, c) not in taken and 0 <= r <= st.body1 and 0 <= c < cv.cols:
                        cv.text(r, c, CUT, RED)
                        taken.add((r, c))
                        break
        for (a, b), label in self.labels.items():  # a word on a link, where it does not cover anything
            way = self.ring.path(st, a, b)
            if way is None:
                continue
            words, colour = ((label,), OUTLINE) if isinstance(label, str) else label
            mx, my = along(way, 0.5)
            for word in filter(None, words):
                r, c = int(my) // 4, round(mx / 2 - len(word) / 2)
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
        for a, b, p, col in self.hops:
            way = self.ring.path(st, a, b)
            if way is None:
                continue
            if self.two_way and a >= 0 and b >= 0 and len(way) == 2:
                way = list(lane((way[0], way[1]), LANE))
            st.cv.blob(*along(way, p), col, 6, 1)
