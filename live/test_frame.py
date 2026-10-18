import pytest

from core.testing import build_world
from live.canvas import Style, plain, vis
from live.frame import CHART_ROWS, compose, layout
from live.__main__ import main
from live.ptyrun import run_in_pty


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
    labels = lines[-4]  # 104 columns: 52 seconds at 2 columns each, the last at 1:39
    assert "0:50" in labels and "1:40" in labels and "0:40" not in labels
    early = frame(world, 10.0)
    plot = early[-4 - CHART_ROWS:-4]
    # Only 10 seconds are drawn: the right part of every chart row is empty but the limit.
    assert all(not row[30:].replace("-", "").strip() for row in plot)


def test_chart_moves_a_whole_second_at_a_time(world):
    """Within a second the chart does not change at all (no bar twitching between widths); when the next
    second comes, everything moves BAR columns to the left."""
    from live.frame import BAR

    def chart(t):
        return [row[5:] for row in frame(world, t)[-4 - CHART_ROWS:-4]]

    assert chart(100.05) == chart(100.5) == chart(100.95)
    now, later = chart(100.5), chart(101.5)
    if frame(world, 100.5)[-4 - CHART_ROWS][:4] == frame(world, 101.5)[-4 - CHART_ROWS][:4]:  # the same scale
        assert all(a[BAR:-BAR] == b[:-2 * BAR] for a, b in zip(now, later))


def test_listing_labs(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "retry_storm" in out and "caching" in out


def test_one_frame_cli(capsys):
    assert main(["retry_storm", "--at", "25", "--size", "110x44"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(" Retry storm") and len(out) <= 44


def test_live_viewer_in_a_pty_quits_cleanly():
    status, text = run_in_pty(["-m", "live", "retry_storm", "--variant", "reference"], keys=b" \x1b[C\x1b[A0q",
                              ready=(b"Behavior:", b"Your stage shows"))
    assert status == 0, text[-500:]
    assert "\x1b[?1049h" in text and "\x1b[?1049l" in text
    assert "Traceback" not in text


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


def test_a_recorded_session_replays_by_itself(tmp_path):
    script = tmp_path / "keys.jsonl"
    script.write_text('{"t": 0.4, "key": "space"}\n{"t": 0.8, "key": "up"}\n{"t": 1.2, "key": "q"}\n')
    status, text = run_in_pty(["-m", "live", "retry_storm", "--variant", "reference", "--replay", str(script)])
    assert status == 0, text[-500:]  # it quit on the replayed q
    assert "Traceback" not in text


def test_recording_writes_every_key_with_its_time(tmp_path):
    log = tmp_path / "rec.jsonl"
    status, text = run_in_pty(["-m", "live", "retry_storm", "--variant", "reference", "--record", str(log)],
                              keys=b"v q", ready=(b"Behavior:", b"Your stage shows"))
    assert status == 0, text[-500:]
    import json

    keys = [json.loads(line)["key"] for line in log.read_text().splitlines()]
    assert keys == ["v", "space", "q"]
