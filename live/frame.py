"""One screenful, drawn from (world, variant, time). No state, so any moment can be rendered on its own (the
chart keeps its last lines, a cache: the same inputs give the same lines, it is only redrawn when they change).

`compose(...)` returns painted lines: the header with the clock top right, the picture with the panel
beside it, the chart (a bar per second, the limit dashed, incidents shaded), and the footer.
"""

from __future__ import annotations

import textwrap

from core.i18n import screen_text
from live.canvas import BLUE, DIM, EXTRA2, GREEN, INK, LIMIT, MUTED, PURPLE, RED, RGB, Canvas, Style, vis
from live.panel import EMPTY, fit_words, panel, split_row
from live.views import render
from live.worlds.base import clock

MIN_COLS = 92
MIN_ROWS = 27
MAX_COLS = 124
CHART_ROWS = 6
BAR = 2  # columns per second on the chart: every second as wide as the others, so bars never change width
EIGHTHS = " ▁▂▃▄▅▆▇█"
KEYS = [("pause", "space"), ("restart", "0"), ("rerun", "r"), ("view", "v"), ("quit", "q"), ("help", "?")]  # ? lists all


def layout(cols: int, rows: int) -> dict[str, int]:
    width = min(cols, MAX_COLS)
    body = max(12, min(28, rows - 16))
    picture = max(50, min(68, width - 38))
    return dict(width=width, body=body, picture=picture, panel=width - picture - 2, chart=CHART_ROWS)


def window(t: float, cols: int) -> tuple[int, int]:
    """The seconds the chart shows, [lo, hi): as many as fit at BAR columns each. It moves a whole second at a
    time, once the run has filled it, so a bar keeps its place and its width until the next second comes."""
    n = max(1, cols // BAR)
    lo = max(0, int(t) - n)
    return lo, lo + n


def nice(v: float) -> float:
    for step in (5, 10, 20, 30, 50, 100, 150, 200, 250, 300, 400, 450, 500, 600, 800, 1000, 1500, 2000, 3000, 5000):
        if v <= step:
            return float(step)
    return float(int(v) + 1)


_chart_cache: tuple = (None, None, None)  # (world, inputs, lines): the last chart drawn


def bar_chart(world, v: str, t: float, cols: int, rows: int, style: Style) -> list[str]:
    """A bar per second up to now, stacked in the same colours as the picture, the limit as a dashed line and
    the incidents that have started shaded. Nothing is drawn for the future. Every second is BAR columns wide.

    A dirty flag: the chart only changes when a second ends (or the scale, the shading, the size or the run do),
    so between those the last lines are given again instead of being drawn 30 times a second."""
    global _chart_cache
    lo, hi = window(t, cols)
    run = world.runs.get(v)
    bands = world.bands(v, t)
    shade = tuple((int(a), -int(-b // 1), rgb) for a, b, rgb in bands)  # the whole seconds each band covers
    key = (v, run, int(t), cols, rows, style.mode, shade)
    cached_world, cached_key, lines = _chart_cache
    if cached_world is world and cached_key == key:
        return lines
    lines = _draw_chart(world, v, t, lo, hi, cols, rows, style, bands)
    _chart_cache = (world, key, lines)
    return lines


def _draw_chart(world, v: str, t: float, lo: int, hi: int, cols: int, rows: int, style: Style,
                bands: list) -> list[str]:
    stacks = world.stacks(v)
    lim = world.chart_limit()
    limit = lim[0] if lim else None
    now = int(t)
    totals = [sum(vals[s] if s < len(vals) else 0 for _, vals in stacks) for s in range(lo, now)]
    top = max(world.chart_top, nice(max(totals + [limit * 1.2 if limit else 0])))
    lim_r = int(limit / top * rows) if limit else None  # the row (from the bottom) the limit runs through
    dash = "┄" if style.mode != "none" else "-"
    # Each second once (not once per cell): its stack, its total, its band.
    seconds = []
    for sec in range(lo, hi):
        parts = [(vals[sec] if sec < len(vals) else 0, rgb) for rgb, vals in stacks] if sec < now else []
        band = next((rgb for a, b, rgb in bands if a <= sec < b), None)
        seconds.append((parts, sum(n for n, _ in parts), band))
    out = []
    for r in range(rows - 1, -1, -1):
        cells = []  # (character, colour, band) for each column
        for c in range(cols):
            k = c // BAR
            if k >= len(seconds):
                cells.append((" ", EMPTY, None))
                continue
            parts, total, band = seconds[k]
            ch, col = " ", EMPTY
            h = total / top * rows * 8 - r * 8 if parts else 0
            if h > 0:
                mid, cum = min(total - 0.01, (r + 0.5) / rows * top), 0.0
                col = parts[-1][1]
                for n, pc in parts:
                    if cum <= mid < cum + n:
                        col = pc
                        break
                    cum += n
                if h < 8:  # the top cell: the colour of the highest layer
                    col = next(pc for n, pc in reversed(parts) if n > 0)
                ch = "█" if h >= 8 else EIGHTHS[max(1, int(h))]
            if ch == " " and r == lim_r:
                ch, col = dash, LIMIT
            cells.append((ch, col, band if style.mode != "none" else None))
        tick = {rows - 1: f"{top:.0f}", 0: "0"}.get(r, f"{limit:.0f}" if r == lim_r else "")
        out.append(f"{style.paint(f'{tick:>4}', LIMIT if r == lim_r and tick else MUTED)} " + _runs(cells, style))
    return out


def _runs(cells: list[tuple[str, RGB, RGB | None]], style: Style) -> str:
    """A row of cells painted a run at a time: one colour code for each run of cells in the same colours,
    not one for every cell (fewer bytes to the terminal)."""
    out, i = [], 0
    while i < len(cells):
        j = i
        while j < len(cells) and cells[j][1:] == cells[i][1:]:
            j += 1
        _, col, band = cells[i]
        text = style.paint("".join(ch for ch, _, _ in cells[i:j]), col)
        out.append(style.bg(band) + text + style.reset if band else text)
        i = j
    return "".join(out)


def axis(t: float, cols: int) -> str:
    """Clock labels every 10 s under the chart, each centred on the start of its second's bar."""
    lo, hi = window(t, cols)
    cells = [" "] * cols
    for sec in range(-(-lo // 10) * 10, hi + 1, 10):
        label = clock(sec)
        at = (sec - lo) * BAR - (len(label) // 2 if sec > lo else 0)
        pos = max(0, min(cols - len(label), at))
        cells[pos:pos + len(label)] = label
    return "".join(cells)


def clock_text(t: float, mode: str, speed: float, style: Style) -> str:
    p = style.paint
    sc = screen_text()
    match mode:
        case "paused":
            return p("❚❚ ", MUTED) + style.bold(p(clock(t), INK)) + p(f"  {sc.PAUSED}", MUTED)
        case "simulating":
            return p("… ", MUTED) + style.bold(p(clock(t), INK)) + p(f"  {sc.SIMULATING}", MUTED)
        case _:
            return p("▶ ", GREEN) + style.bold(p(clock(t), INK)) + p(f"  {speed:g}x", MUTED)


def menu(width: int, style: Style, views: int = 1) -> str:
    """The keys, as "pause/resume [space] - restart [0] - rerun [r] - quit [q]" (and view [v]
    when a lab has more than one picture)."""
    p = style.paint
    words = screen_text().MENU
    keys = [(words[a], k) for a, k in KEYS if a != "view" or views > 1]
    sep = " - " if len(" " + " - ".join(f"{a} [{k}]" for a, k in keys)) < width else "  "
    return " " + p(sep, MUTED).join(p(a + " ", MUTED) + p(f"[{k}]", INK) for a, k in keys)


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner(elapsed: float) -> str:
    return SPINNER[int(elapsed * 10) % len(SPINNER)]


def _about(world) -> tuple[str, str, str]:
    """The lab's one-line summary, the lesson's one-liner, and the first thing to watch for."""
    from core.contract import lesson_of, meta_of

    try:
        lesson = lesson_of(world.id)
        return meta_of(world.id).get("summary", ""), lesson.one_liner, (lesson.watch_for or ("",))[0]
    except (ImportError, AttributeError):
        return "", "", ""


def _card(rows: list[str], width: int, height: int) -> list[str]:
    """Rows centred as a block in an area `width` x `height`."""
    w = max((vis(r) for r in rows), default=0)
    left = " " * max(1, (width - w) // 2)
    top = max(0, (height - len(rows)) // 2)
    out = [""] * top + [left + r for r in rows]
    return (out + [""] * height)[:height]


def edit_file(world, variant: str = "main") -> str:
    """The file the window runs, as you would type it: your main.py (in your language), the reference, or the
    file you gave with --variant."""
    from core.contract import ROOT, module_path

    if not isinstance(variant, str) or variant == "main" or not world.id:  # tests pass code objects too
        return world.files[0] if world.files else f"labs/{world.id}/main.py"
    path = module_path(world.id, variant)
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def loading_card(world, step: str, elapsed: float, width: int, height: int, style: Style,
                 variant: str = "main") -> list[str]:
    """What is happening while the first minute is simulated: each step, ticked off as it is done."""
    p = style.paint
    sc = screen_text()
    files = edit_file(world, variant)
    spin = p(spinner(elapsed), BLUE)
    done, todo = p("✔", GREEN), p("·", DIM)
    loaded = step != "starting"
    steps = [
        (done, sc.STEP_PROCESS, ""),
        (done if loaded else spin, sc.STEP_LOADED.format(file=files), "" if loaded else f"{elapsed:.1f}s"),
        (spin if loaded else todo, sc.STEP_SIMULATING, f"{elapsed:.1f}s" if loaded else ""),
    ]
    inner = min(68, width - 6)
    rows = [style.bold(p(f"{spinner(elapsed)}  " + sc.STARTING.format(title=world.title), INK)), ""]
    for mark, text, when in steps:
        rows.append(split_row(f"{mark}  " + p(text, INK if mark != todo else MUTED), p(when, MUTED), inner))
    rows.append("   " + p(sc.STEP_WHAT, MUTED))
    summary, one_liner, watch = _about(world)
    if one_liner or watch:
        rows += ["", p(sc.WHILE_YOU_WAIT, PURPLE)]
        for text in (one_liner, sc.WATCH_FOR.format(text=watch) if watch else ""):
            rows += [p(line, MUTED) for line in textwrap.wrap(text, inner)] if text else []
    if elapsed > 8:
        rows += [""] + [p(line, EXTRA2) for line in
                        textwrap.wrap(sc.STILL_SIMULATING.format(seconds=f"{elapsed:.0f}"), inner)]
    return _card(rows, width, height)


def split_error(error: str) -> tuple[str, str]:
    """An error from the runner: (message, where to edit), or (message, "") if it names no file."""
    head = screen_text().EDIT_HERE.split("{where}")[0]  # "edit " / "edita "
    message, sep, where = error.partition(f"  ({head}")
    return (message, where.rstrip(")")) if sep else (error, "")


def help_card(width: int, height: int, style: Style) -> list[str]:
    """Every key and what it does (key ?)."""
    p = style.paint
    sc = screen_text()
    rows = [style.bold(p(sc.HELP_TITLE, INK)), ""]
    rows += [p(f"{key:>6}  ", INK) + p(what, MUTED) for key, what in sc.HELP]
    return _card(rows, width, height)


def error_card(world, error: str, width: int, height: int, style: Style) -> list[str]:
    """Your code stopped before the first minute was ready: what happened and where to fix it."""
    p = style.paint
    sc = screen_text()
    message, where = split_error(error)
    inner = min(76, width - 6)
    rows = [style.bold(p(f"✖  {sc.STOPPED_WITH_ERROR}", RED)), ""]
    rows += [p(line, INK) for line in textwrap.wrap(message, inner)[:6]]
    if where:
        rows += ["", p(f"{sc.EDIT} ", MUTED) + style.bold(p(where, INK))]
    rows += ["", p(sc.FIX_AND_SAVE, MUTED)]
    return _card(rows, width, height)


def compose(world, variant: str, t: float, cols: int, rows: int, *, style: Style | None = None,
            mode: str = "play", speed: float = 1.0, status: tuple[str, RGB] | None = None,
            error: str | None = None, loading: tuple[str, float] | None = None,
            views: int = 1, help: bool = False) -> list[str]:
    style = style or Style("none")
    sc = screen_text()
    if cols < MIN_COLS or rows < MIN_ROWS:
        return [sc.TOO_SMALL.format(cols=cols, rows=rows, min_cols=MIN_COLS, min_rows=MIN_ROWS,
                                    best="110x44")[:cols]]
    L = layout(cols, rows)
    W = L["width"]
    p = style.paint
    run = world.runs.get(variant)
    out: list[str] = []

    # The header: the lab, the clock top right, the challenge, what your code does now.
    title = style.bold(p(f" {world.title}", INK))
    if run:
        right = clock_text(t, mode, speed, style)
    elif error:
        right = p(f"✖ {sc.STOPPED}", RED)
    else:
        right = p(f"{spinner(loading[1] if loading else 0)} {sc.LOADING}", BLUE)
    out.append(split_row(title, right, W - 1))
    verdict = world.verdict_at(variant) if run else None
    stage = world.stage(variant) if run and (verdict is None or t >= verdict) else None  # not before its time
    if stage:
        out.append(p(fit_words(f" {stage.story}", W), MUTED))
        lead = f"{sc.BEHAVIOR} "
        out.append(" " + p(lead, MUTED) + style.bold(p(stage.label, stage.colour))
                   + p(f"   → {stage.next}"[: max(0, W - len(stage.label) - len(lead) - 3)], MUTED))
    else:
        hint = sc.STAGE_AT.format(clock=clock(verdict)) if run and verdict is not None else ""
        out += [p(fit_words(f" {_about(world)[0]}", W), MUTED), p(fit_words(f" {hint}", W), MUTED) if hint else ""]
    out.append("")

    body = L["body"]
    if run is None:
        area = body + L["chart"] + 3  # the picture, the panel and the chart are not there yet
        if error:
            out += error_card(world, error, W, area, style)
        else:
            step, elapsed = loading or ("starting", 0.0)
            out += loading_card(world, step, elapsed, W, area, style, variant)
    elif help:  # key ?: the keys instead of the picture, the panel and the chart
        out += help_card(W, body + L["chart"] + 3, style)
    else:
        cv = Canvas(L["picture"], body)
        render(world, cv, variant, t)  # the lab's picture (lanes), fed by its adapter
        side = panel(world, variant, t, L["panel"] - 1, body, style)
        out += [g + "  " + s for g, s in zip(cv.render(style), side)]
        out.append("")
        out += bar_chart(world, variant, t, W - 6, L["chart"], style)
        out.append("     " + p(axis(t, W - 6), MUTED))
        out.append("")

    # The footer: where your code lives, then the keys (or what is going on).
    files = edit_file(world, variant)
    footer = " " + sc.EDIT_AND_SAVE.format(file=files)
    out.append(p(footer if len(footer) <= W else footer[: W - 1] + "…", MUTED))  # a long path never overflows
    if error and run is not None:
        out.append(" " + p(sc.ERROR.format(error=error)[: W - 2], RED))
    elif run is None:
        out.append(" " + p(f"{sc.MENU['quit']} ", MUTED) + p("[q]", INK))
    elif status:
        out.append(" " + p(status[0][: W - 2], status[1]))
    else:
        out.append(menu(W, style, views))
    return out

