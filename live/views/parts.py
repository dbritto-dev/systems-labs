"""The parts the lanes family of pictures is built from (the Component pattern).

A picture is a list of parts drawn in order on one `Stage` (the canvas and the geometry they share: the
users grid on the left, the middle line, the body rows). The lanes view, and its variations relay and
fan-out, are just different lists:

    lanes   UsersGrid, Wire, Door, Flights, Outcomes, Server, Caption
    relay   UsersGrid, Wire×3, Door, Flights, Outcomes, Hops, Server×2, Caption×2
    fan-out UsersGrid, Wire×2, Door, Flights, Outcomes, Leaves, FanHops, Server, Caption×2

A new variation is a new list (and, rarely, a new part), not another copy of the drawing code.
Positions are in Braille dots (2 per column, 4 per row) unless a name says rows or cols.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from live.canvas import BG, BLUE, DIM, RED, RGB, WHITE, Canvas, mix

GRID_COLS = 5  # users per row in the grid
IDLE: RGB = (52, 58, 70)  # a user with nothing in flight
LINE: RGB = (46, 52, 64)  # the dotted lines requests travel along
OUTLINE: RGB = (130, 140, 155)  # a server's case
LABEL_COLS = 10  # room for a small server's name, right of it


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
                ym = mids[j]
                if back:  # on its way back: the same easing and trail, from the small server to the relay
                    moving_dot(st.cv, lambda e, ym=ym: (sx + (x0 - 3 - sx) * (1 - e), st.ymid + (ym - st.ymid) * (1 - e)),
                               p, col, 1)
                else:
                    moving_dot(st.cv, lambda e, ym=ym: (sx + (x0 - 3 - sx) * e, st.ymid + (ym - st.ymid) * e), p, col, 1)


def draw_parts(st: Stage, parts: list) -> None:
    """Draw a picture: each part, in order (later parts on top)."""
    for part in parts:
        part.draw(st)
