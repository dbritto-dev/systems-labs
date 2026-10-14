import os
import pty
import subprocess
import sys
import time

from live.canvas import BLUE, RED, WHITE, Canvas, Style, vis
from live.runner import Job
from live.screen import parse


def test_braille_bits():
    cv = Canvas(2, 1)
    cv.dot(0, 0, WHITE)
    assert cv.plain() == ["\u2801 "]
    for x, y in [(1, 0), (0, 1), (1, 1), (0, 2), (1, 2), (0, 3), (1, 3)]:
        cv.dot(x, y, WHITE)
    assert cv.plain()[0][0] == "\u28ff"
    cv.dot(3, 3, WHITE)
    assert cv.plain()[0][1] == "\u2880"
    cv.dot(99, 99, WHITE)  # off canvas: ignored


def test_higher_priority_wins_the_cell_colour():
    cv = Canvas(1, 1)
    cv.dot(0, 0, RED, 5)
    cv.dot(1, 1, BLUE, 1)
    assert cv.cell(0, 0)[1] == RED
    cv.dot(1, 2, BLUE, 9)
    assert cv.cell(0, 0)[1] == BLUE


def test_text_covers_dots_and_render_modes():
    cv = Canvas(4, 1)
    cv.line([(0, 0), (7, 0)], WHITE)
    cv.text(0, 1, "ab", RED)
    assert cv.plain()[0][1:3] == "ab"
    assert cv.render(Style("none")) == cv.plain()
    assert "\x1b[38;2;248;81;73m" in cv.render(Style("true"))[0]
    assert "\x1b[38;5;" in cv.render(Style("256"))[0]
    assert vis(Style("true").paint("abc", RED)) == 3


def test_key_parsing():
    assert parse("q \x1b[A\x1b[D\x1b[C\x1b[B0r") == [
        "q", "space", "up", "left", "right", "down", "0", "r"]
    assert parse("\x1b") == ["esc"]
    assert parse("\x1b[200~x") == ["x"]


def forever(variant, **params):
    while True:
        pass


def boom(variant, **params):
    raise ValueError(f"bad {variant}")


def echo(variant, **params):
    return {"variant": variant, **params}


def test_job_returns_data():
    assert Job("live.test_toolkit:echo", "main", {"chunk": 2}).run_sync() == (
        "ok", {"variant": "main", "chunk": 2})


def test_job_reports_errors():
    status, msg = Job("live.test_toolkit:boom", "main").run_sync()
    assert status == "error" and "ValueError: bad main" in msg


def test_endless_job_is_killed_with_a_clear_message():
    t0 = time.monotonic()
    status, msg = Job("live.test_toolkit:forever", "main", timeout=1.0).run_sync()
    assert status == "error" and "endless loop" in msg
    assert time.monotonic() - t0 < 5


SCRIPT = """
from live.screen import Terminal
with Terminal() as term:
    term.show(["hello", "world"])
    term.keys(0.05)
print("bye")
"""


def test_terminal_enters_and_leaves_alternate_screen_in_a_pty():
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, "-c", SCRIPT])
    out = b""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    os.waitpid(pid, 0)
    text = out.decode()
    assert "\x1b[?1049h" in text and "\x1b[?1049l" in text
    assert text.index("\x1b[?1049h") < text.index("hello") < text.index("\x1b[?1049l")
    assert "Traceback" not in text and "bye" in text


def test_a_widget_head_never_overflows():
    from live.canvas import Style, vis
    from live.panel import widget

    style = Style("none")
    head = widget("A title far too long for this narrow widget", "and a subtitle", [], 20, style)[0]
    assert vis(head) <= 20 and "…" in head
    head = widget("Users", "waits: the last five seconds", [], 20, style)[0]
    assert vis(head) <= 20 and head.startswith("▍Users")
