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
            x = st.gx + (self.door - 3 - st.gx) * k
            y = y0 + (st.ymid - y0) * min(1.0, k / 0.2)
            st.cv.blob(x, y, col, 6, 2 if big else 1)


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
            st.cv.blob(self.x0 + (self.x1 - self.x0) * k, st.ymid, col, 6, 2 if big else 1)


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
    """The small servers stacked between x0 and x1, a slanted dotted line from `sx` (on the middle line) to
    each, and their names: beside them, or top to bottom in capitals when `vertical`."""

    leaves: list[Leaf]
    x0: float
    x1: float
    sx: float
    vertical: bool = False
    mids: list[float] = field(default_factory=list)  # filled when drawn: each one's middle, for FanHops

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
        self.mids = []
        for j, leaf in enumerate(self.leaves):
            y0, y1 = boxes[j]
            ym = (y0 + y1) / 2
            self.mids.append(ym)
            steps = max(1, int((self.x0 - 2 - self.sx) / 3))
            for s in range(steps + 1):
                p = s / steps
                cv.dot(self.sx + (self.x0 - 2 - self.sx) * p, st.ymid + (ym - st.ymid) * p, LINE, 0)
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
                cv.text(min(h - 2, int(ym // 4)), self.x1 // 2 + 2, text[:LABEL_COLS - 1], col)


@dataclass(slots=True)
class FanHops:
    """Requests between the relay and a small server, along that server's slanted line (or back)."""

    hops: list[tuple[int, float, RGB, bool]]  # (leaf, 0..1, colour, back)
    leaves: Leaves  # drawn first: it knows where each small server sits

    def draw(self, st: Stage) -> None:
        mids, sx, x0 = self.leaves.mids, self.leaves.sx, self.leaves.x0
        for j, p, col, back in self.hops:
            if 0 <= j < len(mids):
                p = 1 - p if back else p
                st.cv.blob(sx + (x0 - 3 - sx) * p, st.ymid + (mids[j] - st.ymid) * p, col, 6, 1)


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
    out of the line: drawn after a gap, dimmed. Their names go on the two rows under the picture
    (the last one only from column `free_from`, after the state): the full label if it fits, else the
    short form, else the tiny one."""

    boxes: list[Leaf]
    x0: float
    x1: float
    gap_after: int | None = None
    free_from: int = 0
    xs: list[float] = field(default_factory=list)  # each box's centre (set when made)
    rx: float = 0.0  # half a box's width

    def __post_init__(self) -> None:
        n = len(self.boxes)
        out = self.gap_after is not None and self.gap_after < n - 1
        slot = (self.x1 - self.x0) / max(1, n + (GAP_SLOTS if out else 0))
        w = max(4.0, min(16.0, slot - 6))
        self.rx = float(int(w / 2))  # whole dots, so both sides of every box look the same
        gap = [slot * GAP_SLOTS if out and j > self.gap_after else 0.0 for j in range(n)]
        self.xs = [float(round(self.x0 + slot * (j + 1) - w / 2 + gap[j])) for j in range(n)]  # a segment, then the box

    def dimmed(self, j: int) -> bool:
        return self.gap_after is not None and j > self.gap_after

    def seg(self, k: int) -> tuple[float, float]:
        """Where segment k starts and ends, in dots (the first and last dot a request is drawn at)."""
        left = self.x0 + 2 if k == 0 else self.xs[k - 1] + self.rx + 2
        return left, self.xs[k] - self.rx - 3

    def x_of(self, j: int) -> float:
        """Box j's centre (-1: the door)."""
        return self.x0 if j < 0 else self.xs[j]

    @staticmethod
    def span(st: Stage) -> tuple[int, int]:
        """A box's top and bottom, in dots: room above for the arcs, and a row below for the names."""
        return st.top + 8, st.bottom - 4

    def draw(self, st: Stage) -> None:
        cv = st.cv
        y0, y1 = self.span(st)
        last = self.gap_after if self.gap_after is not None else len(self.boxes) - 1
        for k in range(min(last + 1, len(self.boxes))):  # the dotted line between the door and each box
            a, b = self.seg(k)
            for x in range(int(a), int(b) + 1, 3):
                cv.dot(x, st.ymid, LINE, 0)
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
            at = max(lo[row], min(round(c - len(word) / 2), cv.cols - len(word)))
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
                st.cv.blob(a + (b - a) * max(0.0, min(1.0, p)), st.ymid, col, 6, 1)


@dataclass(slots=True)
class Skip:
    """Requests that skip boxes: each pair (from, to) gets a dotted arc over the boxes, on the band
    above them, and its requests are dots along it (0..1 from `from` to `to`; -1 is the door)."""

    skips: list[tuple[int, int, float, RGB]]  # (from, to, 0..1, colour)
    boxes: Boxes

    def _arcs(self, st: Stage) -> dict[tuple[int, int], object]:
        """Each pair's arc, as a function from 0..1 to (x, y): the longer the arc, the higher it stands
        (so arcs that share an end can be told apart)."""
        n = len(self.boxes.xs)
        pairs = dict.fromkeys((a, b) for a, b, _, _ in self.skips if -1 <= a < n and -1 <= b < n and a != b)
        base = Boxes.span(st)[0] - 1
        most = base - st.top - 1  # the band's height
        spans = sorted({abs(self.boxes.x_of(b) - self.boxes.x_of(a)) for a, b in pairs})
        out = {}
        for a, b in pairs:
            xa, xb = self.boxes.x_of(a), self.boxes.x_of(b)
            rank = spans.index(abs(xb - xa))
            lift = most - (most - 3) * (len(spans) - 1 - rank) / max(1, len(spans) - 1)

            def at(p: float, xa=xa, xb=xb, lift=lift) -> tuple[float, float]:
                x = xa + (xb - xa) * max(0.0, min(1.0, p))
                d = min(abs(x - xa), abs(x - xb))
                return x, base - lift * math.sin(min(1.0, d / 6) * math.pi / 2)

            out[(a, b)] = at
        return out

    def draw(self, st: Stage) -> None:
        arcs = self._arcs(st)
        for (a, b), at in arcs.items():
            steps = max(2, int(abs(self.boxes.x_of(b) - self.boxes.x_of(a)) / 3))
            for s in range(steps + 1):
                st.cv.dot(*at(s / steps), LINE, 0)
        for a, b, p, col in self.skips:
            if (a, b) in arcs:
                st.cv.blob(*arcs[(a, b)](p), col, 6, 1)


def draw_parts(st: Stage, parts: list) -> None:
    """Draw a picture: each part, in order (later parts on top)."""
    for part in parts:
        part.draw(st)
