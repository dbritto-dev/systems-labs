import os
import pty
import select
import sys
import time

import pytest

from core.testing import build_world
from live.canvas import Style, plain, vis
from live.frame import CHART_ROWS, compose, layout
from live.__main__ import main


@pytest.fixture(scope="module")
def world():
    return build_world("retry_storm", "reference", 2)


def frame(world, t, cols=110, rows=44, **kw) -> list[str]:
    return [plain(line) for line in compose(world, "reference", t, cols, rows, **kw)]


@pytest.mark.parametrize("size", [(92, 30), (110, 44), (200, 70)])
def test_nothing_overflows(world, size):
    cols, rows = size
    width = layout(cols, rows)["width"]
    for t in (0.0, 25.0, 59.0, 100.0):
        for style in (Style("none"), Style("true")):
            lines = compose(world, "reference", t, cols, rows, style=style, status=("running your code…", (1, 2, 3)))
            assert len(lines) <= rows and all(vis(line) <= width for line in lines)
        text = "\n".join(frame(world, t, cols, rows))
        assert "Baseline ok" in text and "Load < 1.5x" in text  # the goals stay on screen
        assert "Edit labs/retry_storm/reference.py" in text  # the footer names the file the window runs


def test_small_terminal_gets_one_line(world):
    lines = frame(world, 10.0, 80, 30)
    assert len(lines) == 1 and "at least 92" in lines[0]


def test_header_clock_and_menu(world):
    lines = frame(world, 100.0, mode="play", speed=2.0)
    assert lines[0].startswith(" Retry storm") and lines[0].rstrip().endswith("▶ 1:40  2x")
    assert lines[2].startswith(" Behavior: Retry + backoff + jitter + budget")
    assert lines[-1].startswith(" pause/resume [space] - restart [0] - rerun [r] - quit [q]")
    assert frame(world, 100.0, mode="paused")[0].rstrip().endswith("❚❚ 1:40  paused")


def test_panel_widgets_like_a_dashboard(world):
    text = "\n".join(frame(world, 32.0))
    for part in ("▍Users", "waits: last 5 s", "▍Calls", "per second, last 1 s", "╷ limit 150/s",
                 "▍Outage #1", "OK ·", "▍Events", "so far", "HEALTHY"):
        assert part in text, part
    text = "\n".join(frame(world, 21.0))
    assert "▼ DOWN" in text and "is down:" in text


def test_chart_scrolls_and_never_draws_the_future(world):
    lines = frame(world, 100.0)
    labels = lines[-4]
    assert "0:40" in labels and "1:40" in labels and "0:30" not in labels
    early = frame(world, 10.0)
    plot = early[-4 - CHART_ROWS:-4]
    # Only 10 of 60 seconds are drawn: the right part of every chart row is empty but the limit.
    assert all(not row[30:].replace("-", "").strip() for row in plot)


def test_listing_labs(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "retry_storm" in out and "caching" in out


def test_one_frame_cli(capsys):
    assert main(["retry_storm", "--at", "25", "--size", "110x44"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(" Retry storm") and len(out) <= 44


def test_live_viewer_in_a_pty_quits_cleanly():
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["COLUMNS"], os.environ["LINES"] = "110", "44"
        os.execv(sys.executable, [sys.executable, "-m", "live", "retry_storm", "--variant", "reference"])
    import fcntl
    import struct
    import termios

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 44, 110, 0, 0))
    out = b""
    deadline = time.monotonic() + 15
    sent = False
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        if not sent and b"Behavior:" in out:
            os.write(fd, b" \x1b[C\x1b[A0q")
            sent = True
    _, status = os.waitpid(pid, 0)
    text = out.decode("utf-8", "replace")
    assert sent, text[-500:]
    assert "\x1b[?1049h" in text and "\x1b[?1049l" in text
    assert "Traceback" not in text
    assert os.WEXITSTATUS(status) == 0


def test_loading_screen_ticks_off_each_step():
    from live.worlds import make_world

    world = make_world("retry_storm")
    lines = [plain(x) for x in compose(world, "main", 0.0, 110, 44, loading=("starting", 0.3))]
    text = "\n".join(lines)
    assert "loading" in lines[0] and "Starting Retry storm" in text
    assert "✔  Started a Python process" in text and "Loaded labs/retry_storm/main.py" in text
    assert "·  Simulating the first minute" in text and "While you wait" in text
    assert lines[-1].strip() == "quit [q]" and len(lines) <= 44
    text = "\n".join(plain(x) for x in compose(world, "main", 0.0, 110, 44, loading=("loaded", 9.5)))
    assert "✔  Loaded labs/retry_storm/main.py" in text and "Still simulating after" in text


def test_an_error_before_the_first_minute_says_where_to_fix_it():
    from live.worlds import make_world

    world = make_world("retry_storm")
    error = "TypeError: boom  (edit labs/retry_storm/main.py:38)"
    text = "\n".join(plain(x) for x in compose(world, "main", 0.0, 110, 44, error=error))
    assert "Your code stopped with an error" in text and "TypeError: boom" in text
    assert "Edit labs/retry_storm/main.py:38" in text and "stopped" in text.splitlines()[0]
