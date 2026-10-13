"""The terminal: alternate screen, hidden cursor, raw keys, and redraws of changed lines only."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty

_SEQS = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1b[H": "home", "\x1b[F": "end",
}


def parse(data: str) -> list[str]:
    """Split raw input into key names: 'up', 'left', 'space', 'enter', 'esc', 'q', ..."""
    keys: list[str] = []
    i = 0
    while i < len(data):
        ch = data[i]
        if ch == "\x1b":
            for seq, name in _SEQS.items():
                if data.startswith(seq, i):
                    keys.append(name)
                    i += len(seq)
                    break
            else:
                if data.startswith("\x1b[", i):  # unknown CSI: skip to its final byte
                    j = i + 2
                    while j < len(data) and not ("@" <= data[j] <= "~"):
                        j += 1
                    i = j + 1
                else:
                    keys.append("esc")
                    i += 1
            continue
        match ch:
            case " ":
                keys.append("space")
            case "\r" | "\n":
                keys.append("enter")
            case "\x03":
                keys.append("ctrl-c")
            case _ if ch.isprintable():
                keys.append(ch)
        i += 1
    return keys


class Terminal:
    """Context manager owning the terminal while the viewer runs."""

    def __init__(self, stream=None, fd: int | None = None) -> None:
        self.out = stream or sys.stdout
        self.fd = sys.stdin.fileno() if fd is None else fd
        self._saved = None
        self._lines: list[str] = []
        self._size: tuple[int, int] | None = None

    def __enter__(self) -> "Terminal":
        try:
            self._saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        except termios.error:
            self._saved = None
        self.out.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        self.out.flush()
        return self

    def __exit__(self, *exc) -> None:
        self.out.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        self.out.flush()
        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)

    def size(self) -> tuple[int, int]:
        try:
            s = os.get_terminal_size(self.out.fileno())
            return s.columns, s.lines
        except (OSError, ValueError):
            return 110, 44

    def show(self, lines: list[str]) -> None:
        """Draw the frame, rewriting only the lines that changed."""
        size = self.size()
        buf = []
        if size != self._size:
            self._size = size
            self._lines = []
            buf.append("\x1b[0m\x1b[2J")
        for i, line in enumerate(lines):
            if i < len(self._lines) and self._lines[i] == line:
                continue
            buf.append(f"\x1b[{i + 1};1H{line}\x1b[0m\x1b[K")
        for i in range(len(lines), len(self._lines)):
            buf.append(f"\x1b[{i + 1};1H\x1b[0m\x1b[K")
        self._lines = list(lines)
        if buf:
            self.out.write("".join(buf))
            self.out.flush()

    def keys(self, timeout: float) -> list[str]:
        """Keys pressed within `timeout` seconds (empty if none)."""
        try:
            ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        except (OSError, ValueError):
            return []
        if not ready:
            return []
        data = os.read(self.fd, 1024).decode("utf-8", "replace")
        if data == "":
            return ["q"]  # stdin closed
        return parse(data)
