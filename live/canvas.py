"""A character-cell canvas that draws with Braille dots (2 x 4 dots per cell) and one colour per cell,
and `Style`, which paints strings with ANSI colours.

Each cell is 2 dots wide and 4 dots tall. `dot(x, y, rgb, prio)` sets one dot; a cell has one colour, and
the dot with the highest priority picks it. Text written with `text()` sits on top of the dots.
"""

from __future__ import annotations

import math
import os
import re
import sys

type RGB = tuple[int, int, int]

# The palette. Orange shades mean "extra work": a retry round, a cache miss, a duplicate load.
BG: RGB = (13, 17, 23)
INK: RGB = (230, 237, 243)
WHITE: RGB = (210, 218, 226)  # first tries and normal requests
EXTRA1: RGB = (250, 190, 135)
EXTRA2: RGB = (240, 136, 62)
EXTRA3: RGB = (186, 86, 22)
EXTRA: tuple[RGB, ...] = (WHITE, EXTRA1, EXTRA2, EXTRA3)
ORANGE: RGB = EXTRA2
RED: RGB = (248, 81, 73)
GREEN: RGB = (63, 185, 80)
BLUE: RGB = (88, 166, 255)  # healthy / fixed
MUTED: RGB = (139, 148, 158)
DIM: RGB = (72, 80, 92)
IDLE_DOT: RGB = (110, 118, 132)
LIMIT: RGB = (255, 120, 140)
PURPLE: RGB = (124, 82, 214)
YELLOW: RGB = (230, 200, 70)  # more kinds of trouble, when a lab needs a colour for each
PINK: RGB = (236, 110, 180)

_BIT = ((1, 2, 4, 64), (8, 16, 32, 128))  # [dx][dy] -> Braille bit
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def mix(a: RGB, b: RGB, k: float) -> RGB:
    """Blend from a (k=0) to b (k=1)."""
    k = max(0.0, min(1.0, k))
    return (int(a[0] + (b[0] - a[0]) * k), int(a[1] + (b[1] - a[1]) * k), int(a[2] + (b[2] - a[2]) * k))


def vis(s: str) -> int:
    """How many columns a painted string takes."""
    return len(_ANSI.sub("", s))


def plain(s: str) -> str:
    """A painted string without its colours."""
    return _ANSI.sub("", s)


class Style:
    """ANSI colours: 24-bit when the terminal says it can, else the 256-colour cube, else none."""

    def __init__(self, mode: str | None = None) -> None:
        if mode is None:
            if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
                mode = "none"
            elif os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
                mode = "true"
            else:
                mode = "256"
        if mode not in ("true", "256", "none"):
            raise ValueError(f"colour mode must be true, 256 or none, not {mode!r}")
        self.mode = mode
        # Flyweight: one escape code per colour, built once (a frame paints a few thousand times, with a
        # few dozen colours).
        self._fg: dict[RGB, str] = {}
        self._bg: dict[RGB, str] = {}

    def _code(self, rgb: RGB) -> str:
        r, g, b = rgb
        if self.mode == "true":
            return f"2;{r};{g};{b}"
        return f"5;{16 + 36 * round(r / 51) + 6 * round(g / 51) + round(b / 51)}"

    def fg(self, rgb: RGB | None) -> str:
        if self.mode == "none" or rgb is None:
            return ""
        code = self._fg.get(rgb)
        if code is None:
            code = self._fg[rgb] = f"\033[38;{self._code(rgb)}m"
        return code

    def bg(self, rgb: RGB | None) -> str:
        if self.mode == "none" or rgb is None:
            return ""
        code = self._bg.get(rgb)
        if code is None:
            code = self._bg[rgb] = f"\033[48;{self._code(rgb)}m"
        return code

    @property
    def reset(self) -> str:
        return "" if self.mode == "none" else "\033[0m"

    def bold(self, s: str) -> str:
        return s if self.mode == "none" else f"\033[1m{s}\033[22m"

    def paint(self, s: str, rgb: RGB | None) -> str:
        return f"{self.fg(rgb)}{s}\033[0m" if self.mode != "none" and rgb else s


class Canvas:
    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.w, self.h = cols * 2, rows * 4
        self.bits = [[0] * cols for _ in range(rows)]
        self.col: list[list[RGB | None]] = [[None] * cols for _ in range(rows)]
        self.prio = [[-1] * cols for _ in range(rows)]
        self.txt: dict[tuple[int, int], tuple[str, RGB | None]] = {}  # text sits on top of the dots

    def dot(self, x: float, y: float, rgb: RGB, prio: int = 0) -> None:
        x, y = int(x), int(y)
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        r, c = y >> 2, x >> 1
        self.bits[r][c] |= _BIT[x & 1][y & 3]
        if prio >= self.prio[r][c]:
            self.prio[r][c], self.col[r][c] = prio, rgb

    def blob(self, x: float, y: float, rgb: RGB, prio: int = 5, radius: int = 1) -> None:
        """A bigger point: a filled square of dots, so a request is easy to see."""
        for dx in range(-radius + 1, radius + 1):
            for dy in range(-radius + 1, radius + 1):
                self.dot(x + dx, y + dy, rgb, prio)

    def ring(self, x: float, y: float, radius: float, rgb: RGB, prio: int = 4) -> None:
        n = max(8, int(radius * 5))
        for i in range(n):
            a = 2 * math.pi * i / n
            self.dot(x + radius * math.cos(a), y + radius * math.sin(a) * 0.9, rgb, prio)

    def line(self, pts: list[tuple[float, float]], rgb: RGB, prio: int = 1) -> None:
        """A polyline through the points."""
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
            for i in range(n + 1):
                k = i / n
                self.dot(x0 + (x1 - x0) * k, y0 + (y1 - y0) * k, rgb, prio)

    def text(self, row: int, col: int, s: str, rgb: RGB | None) -> None:
        for i, ch in enumerate(s):
            if 0 <= row < self.rows and 0 <= col + i < self.cols:
                self.txt[(row, col + i)] = (ch, rgb)

    def cell(self, r: int, c: int) -> tuple[str, RGB | None]:
        if (r, c) in self.txt:
            return self.txt[(r, c)]
        if not self.bits[r][c]:
            return " ", None
        return chr(0x2800 + self.bits[r][c]), self.col[r][c]

    def plain(self) -> list[str]:
        """The rows without colour (for tests)."""
        return ["".join(self.cell(r, c)[0] for c in range(self.cols)) for r in range(self.rows)]

    def render(self, style: Style) -> list[str]:
        out = []
        for r in range(self.rows):
            parts: list[str] = []
            cur: object = object()
            for c in range(self.cols):
                ch, rgb = self.cell(r, c)
                if rgb != cur:
                    parts.append(style.reset + style.fg(rgb) if style.mode != "none" else "")
                    cur = rgb
                parts.append(ch)
            out.append("".join(parts) + style.reset)
        return out
