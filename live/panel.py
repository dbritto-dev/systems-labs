"""The side panel, after a Datadog dashboard: tinted widgets with a small title, query values on a coloured
background, a toplist of calls, monitors with status badges, an event stream, and one legend.

Every function returns painted strings, one per row, `width` columns wide.
"""

from __future__ import annotations

import textwrap

from core.i18n import screen_text
from live.canvas import GREEN, INK, LIMIT, MUTED, PURPLE, RED, RGB, Style, vis
from live.worlds.base import GoalRow, Tile, Traffic, clock

DD_BG: RGB = (24, 28, 38)
DD_TITLE: RGB = (150, 158, 172)
DD_HEAD: RGB = (225, 230, 240)
CAPTION: RGB = (110, 118, 132)
EMPTY: RGB = (48, 54, 64)
FIX_ARROW: RGB = (230, 140, 80)
FADED: RGB = (90, 96, 110)
FADED_BAR: RGB = (70, 76, 90)
EIGHTHS = " ▁▂▃▄▅▆▇█"

# Query values: the number on a background coloured by its state.
DD_STATE: dict[str, tuple[RGB, RGB]] = {
    "ok": ((235, 255, 240), (34, 120, 72)),
    "warn": ((40, 30, 0), (226, 150, 40)),
    "bad": ((255, 235, 235), (176, 40, 56)),
    "idle": ((200, 205, 215), (58, 64, 78)),
}
SEVERITY = {"idle": 0, "ok": 0, "warn": 1, "bad": 2}
STATUS = {"ok": ("●", GREEN), "alert": ("●", RED), "wait": ("○", MUTED)}  # the words: screen.STATUS
EVENT_STYLE: dict[str, tuple[str, RGB]] = {  # by kind, in any language
    "start": ("▼", (226, 60, 76)), "end": ("▲", (52, 168, 100)), "alert": ("✖", (226, 60, 76)),
    "ok": ("✔", (52, 168, 100)), "warn": ("▲", (226, 150, 40)),
}
OTHER_STYLE = ("●", (100, 150, 230))


def split_row(left: str, right: str, width: int) -> str:
    return left + " " * max(1, width - vis(left) - vis(right)) + right


def tinted(row: str, width: int, style: Style, bg: RGB = DD_BG) -> str:
    """A row on the widget background, padded to the width (the background survives the resets inside)."""
    if style.mode == "none":
        return row + " " * max(0, width - vis(row))
    on = style.bg(bg)
    return on + row.replace("\033[0m", "\033[0m" + on) + " " * max(0, width - vis(row)) + style.reset


def widget(title: str, right: str, rows: list[str], width: int, style: Style) -> list[str]:
    p = style.paint
    if len(title) > width - 2:  # never wider than the widget: cut the title, then drop the subtitle
        title = title[:max(0, width - 3)] + "…"
    if right and 1 + len(title) + 1 + vis(right) > width - 1:
        right = ""
    head = p("▍", PURPLE) + style.bold(p(title, DD_HEAD))
    out = [tinted(split_row(head, right, width - 1) if right else head, width, style)]
    return out + [tinted(" " + r, width, style) for r in rows]


# ------------------------------------------------------------------- tiles


def spark(hist: list[tuple[float, str]], n: int, style: Style) -> str:
    """The recent history of a tile as n cells: each the worst of its seconds, as tall as its value and in its
    state's colour, so a tile reads "fine now, red a moment ago"."""
    if not hist or n <= 0:
        return ""
    top = max((abs(v) for v, _ in hist), default=0.0) or 1.0
    per = max(1, -(-len(hist) // n))
    cells = []
    for k in range(0, len(hist), per):
        group = hist[k:k + per]
        val, state = max(reversed(group), key=lambda x: SEVERITY.get(x[1], 0))  # the worst; the latest of equals
        level = max(1, min(8, round(abs(val) / top * 8))) if val else 1
        cells.append(style.paint(EIGHTHS[level], DD_STATE.get(state, DD_STATE["idle"])[1]))
    return "".join(cells[-n:])


def dd_tiles(tiles: list[Tile], width: int, style: Style) -> list[str]:
    """Query values side by side, as wide together as the widgets below them: a small title with the target
    next to it, the value on a background coloured by its state, and the last 30 s as a small bar chart."""
    n = max(1, len(tiles))
    w = (width - (n - 1)) // n
    widths = [w] * (n - 1) + [width - (n - 1) - w * (n - 1)]  # the last tile takes the remainder
    rows = ["", "", ""]
    for i, (tile, wi) in enumerate(zip(tiles, widths)):
        fg, bg = DD_STATE.get(tile.state, DD_STATE["idle"])
        gap = " " if i else ""
        room = max(0, wi - len(tile.title) - 1)
        head = style.paint(f" {tile.title}", DD_TITLE) + style.paint(f"{tile.target:>{room}}"[:room], CAPTION)
        rows[0] += gap + tinted(head, wi, style)
        if style.mode == "none":
            rows[1] += gap + f"[{tile.value:^{wi - 2}}]"
        else:
            rows[1] += gap + style.bg(bg) + style.bold(style.fg(fg) + f"{tile.value:^{wi}}") + style.reset
        rows[2] += gap + tinted(" " + spark(tile.history, wi - 2, style), wi, style)
    return rows


# ------------------------------------------------------------------- toplist


def dd_toplist(tr: Traffic, width: int, style: Style) -> list[str]:
    """A row with the limit named above its tick, then each line: name, a bar (stacked parts keep their
    colours) and the value right where the bar ends; a value never covers the limit tick."""
    p = style.paint
    inner = width - 2
    total = max((sum(v for v, _ in b.segments) for b in tr.bars), default=0.0)
    top = tr.top or max(tr.limit * 1.5, total * 1.05, 1.0)
    bw = inner - 10 - 1
    rows = []
    k = min(bw - 1, int(tr.limit / top * bw)) if tr.limit else None
    if k is not None:
        name = tr.limit_label
        rows.append(" " * (10 + k) + p("╷", LIMIT) + p(" " + name, LIMIT) if k + 2 + len(name) <= bw else
                    " " * max(0, 10 + k - len(name) - 1) + p(name + " ", LIMIT) + p("╷", LIMIT))
    for bar in tr.bars:
        cells: list[tuple[str, RGB] | None] = []
        for i in range(bw):
            x = (i + 0.5) / bw * top
            cum, cell = 0.0, None
            for value, rgb in bar.segments:
                if cum <= x < cum + value:
                    cell = ("█", rgb)
                    break
                cum += value
            cells.append(cell)
        end = max([i + 1 for i, c in enumerate(cells) if c] or [0])
        text = f" {sum(v for v, _ in bar.segments):,.0f}{tr.unit}"
        at = k + 1 if k is not None and end <= k < end + len(text) else end  # never hide the limit tick
        line: list[tuple[str, RGB]] = []
        for i in range(bw):
            if cells[i]:
                line.append(cells[i])
            elif at <= i < at + len(text):
                line.append((text[i - at], INK))
            elif i == k:
                line.append(("│", LIMIT))
            else:
                line.append(("·" if style.mode == "none" else " ", EMPTY))
        if at + len(text) > bw:  # a bar that runs off the scale: its value goes at the end
            body = "".join(p(c, col) for c, col in line[:bw - len(text)]) + style.bold(p(text, INK))
        else:
            body = "".join(style.bold(p(c, col)) if col == INK else p(c, col) for c, col in line)
        rows.append(p(f"{bar.label:<10}"[:10], (210, 216, 226)) + body)
    return rows


# ------------------------------------------------------------------- monitors


def dd_monitors(lines: list[GoalRow], width: int, style: Style) -> list[str]:
    """One monitor per goal: a status dot and word, the rule, its value right after it, and when it is judged
    (before / during / after) when there is room."""
    p = style.paint
    words = screen_text().STATUS
    ww = max(len(w) for w in words.values()) + 1
    lw = max([len(g.rule) for g in lines] or [0]) + 1
    vw = max([len(g.value) for g in lines] or [0])
    tw = max([len(g.phase) for g in lines] or [0])
    room = width - 2 - (ww + 2)
    if lw + max(5, vw) > room:  # a long value: shorten the rules first
        lw = max(8, room - max(5, vw) - 1)
    tags = ww + 2 + lw + max(5, vw) + 1 + tw <= width - 2
    rows = []
    for g in lines:
        dot, col = STATUS[g.status]
        word = words[g.status]
        shown = {"ok": GREEN, "alert": RED}.get(g.status, MUTED)
        rule = g.rule if len(g.rule) < lw else g.rule[:lw - 2] + "…"
        value = g.value[: max(5, room - lw)]
        row = (p(dot, col) + " " + style.bold(p(f"{word:<{ww}}", col)) + p(f"{rule:<{lw}}", INK)
               + style.bold(p(f"{value:>{max(5, vw)}}", shown)))
        if tags:
            row += p(f" {g.phase:>{tw}}", CAPTION)
        rows.append(row)
    return rows


# ------------------------------------------------------------------- events


def dd_events(world, v: str, t: float, width: int, style: Style, rows: int = 4) -> tuple[str, list[str]]:
    """The run's events up to now: time, an icon and verb in its colour, and what it is about. The latest
    alert of this incident stays pinned on top with what to do; the rest follow, newest first. Then the
    next check. Nothing that has not happened yet is shown."""
    p = style.paint
    sc = screen_text()
    inner = width - 3
    seen = [e for e in world.timeline(v) if e.t <= t]
    inc = world.current_incident(v, t)
    alerts = [e for e in seen if e.kind == "alert" and inc is not None and e.incident == inc.index]
    pin = alerts[-1] if alerts else None

    def row(e, dim: bool = False) -> list[str]:
        icon, col = EVENT_STYLE.get(e.kind, OTHER_STYLE)
        c = FADED if dim else col
        head = p("▌", FADED_BAR if dim else col) + p(f"{clock(e.t):>4} ", DD_TITLE) + p(icon + " ", c)
        head += style.bold(p(f"{e.verb[:6]:<7}", c))  # up to 6 letters and a space
        room = inner - 14
        if e.start and len(e.text) > room:  # what went wrong: up to 3 lines, so the cause shows
            first, *rest = textwrap.wrap(e.text, room, max_lines=3, placeholder="…")
            return [head + p(first, INK)] + [p("▌", col) + " " * 13 + p(more, INK) for more in rest]
        return [head + p(e.text[:room], DD_TITLE if dim else INK)]

    out: list[str] = []
    if pin is not None:
        out += row(pin)
        if pin.fix:
            out.append(p("▌", EVENT_STYLE["alert"][1]) + "      " + p("→ ", FIX_ARROW) + p(pin.fix[:inner - 8], INK))
    for e in reversed(seen):
        if e is not pin:
            out += row(e)
    nxt = world.next_check(v, t)
    out = out[:rows - 1] if nxt and len(out) >= rows else out[:rows]
    if len(out) < rows and nxt:
        out.append(p("▌", FADED_BAR) + p("     ○ ", FADED) + style.bold(p(f"{sc.NEXT[:6]:<7}", FADED))
                   + p(nxt[:inner - 14], DD_TITLE))
    right = p(sc.SO_FAR.format(n=len(seen)) if seen else sc.NONE_YET, DD_TITLE)
    return right, out


# ------------------------------------------------------------------- users, legend


def stat_rows(stats: list[tuple[str, str, RGB]], width: int, style: Style) -> list[str]:
    """label value pairs packed into rows: "served 8,473  failed 1,602  waiting 3"."""
    rows, cur, n = [], "", 0
    for label, value, col in stats:
        cell = style.paint(label + " ", DD_TITLE) + style.bold(style.paint(value, col))
        size = len(label) + 1 + len(value)
        if cur and n + 2 + size > width:
            rows.append(cur)
            cur, n = "", 0
        cur, n = (cur + "  " + cell, n + 2 + size) if cur else (cell, size)
    return rows + ([cur] if cur else [])


def legend_rows(items: list[tuple], width: int, style: Style) -> list[str]:
    """The colour key, packed into as few rows as fit. An item is (colour or [colours], name) or
    (colour, name, glyph)."""

    def cell(item: tuple) -> str:
        c, text = item[0], item[1]
        g = item[2] if len(item) > 2 else "●"
        dots = "".join(style.paint(g, x) for x in c) if isinstance(c, list) else style.paint(g, c)
        return dots + " " + style.paint(text, MUTED)

    for sep in ("   ", "  "):
        row = " " + sep.join(cell(it) for it in items)
        if vis(row) <= width:
            return [row]
    rows, cur = [], ""
    for it in items:
        c = cell(it)
        if cur and vis(cur) + 2 + vis(c) > width:
            rows.append(cur)
            cur = ""
        cur = (cur + "  " + c) if cur else " " + c
    return rows + ([cur] if cur else [])


# ------------------------------------------------------------------- the panel


def dd_panel(world, v: str, t: float, tr: Traffic, lines: list[GoalRow], width: int, style: Style,
             level: int = 0, events: int = 4, memo: dict | None = None) -> list[str]:
    """The widgets with a blank row between them; level 1, 2 and 3 drop the events, the tiles and users,
    then the titles and gaps. `memo` keeps what does not depend on the level, while `panel` tries layouts."""
    memo = {} if memo is None else memo

    def once(key, make):
        if key not in memo:
            memo[key] = make()
        return memo[key]

    gap = [] if level >= 3 else [""]
    sc = screen_text()
    out: list[str] = []
    if tr.tiles and level < 2:
        out += once("tiles", lambda: dd_tiles(tr.tiles, width, style))  # their colour sets them apart: no gap
    stats = once("stats", lambda: world.user_stats(v, t))
    if stats and level < 2:
        out += once("users", lambda: widget(sc.USERS, style.paint(sc.WAITS, DD_TITLE),
                                            stat_rows(stats, width - 2, style), width, style)) + gap
    rows = once("calls", lambda: dd_toplist(tr, width, style)
                + [style.bold(style.paint(tr.headline[:width - 2], tr.headline_colour))])
    sub = style.paint(tr.subtitle or sc.PER_SECOND, DD_TITLE)
    out += (widget(tr.title or sc.CALLS, sub, rows, width, style) if level < 3
            else [tinted(" " + r, width, style) for r in rows]) + gap
    ok = sum(g.status == "ok" for g in lines)
    bad = sum(g.status == "alert" for g in lines)
    wait = len(lines) - ok - bad
    title = once("title", lambda: world.goal_title(v, t))
    counts = sc.COUNTS
    full = [(counts["ok"].format(n=ok), GREEN), (counts["alert"].format(n=bad), RED if bad else MUTED),
            (counts["wait"].format(n=wait), MUTED)]
    summary = ""
    for parts in (full, [(s, c) for s, c in full if not s.startswith("0 ")]):  # drop zero counts if needed
        text = " · ".join(s for s, _ in parts)
        if len(title) + len(text) + 3 <= width:
            summary = style.paint(" · ", MUTED).join(style.paint(s, c) for s, c in parts)
            break
    mons = once("monitors", lambda: dd_monitors(lines, width, style))
    out += (widget(title, summary, mons, width, style) if level < 3
            else [tinted(" " + r, width, style) for r in mons])
    if level < 1:
        right, erows = once(("events", events), lambda: dd_events(world, v, t, width, style, events))
        out += gap + widget(sc.EVENTS, right, erows, width, style)
    return out


def panel(world, v: str, t: float, width: int, height: int, style: Style) -> list[str]:
    """The fullest layout that fits `height` rows, so the goals always stay on screen."""
    tr = world.traffic(v, t)
    lines = world.goal_lines(v, t)
    legend = legend_rows(world.legend, width - 1, style)
    notes = [" " + style.paint(note[:width - 1], MUTED) for note in world.legend_notes()]

    memo: dict = {}  # the parts every layout shares, built once

    def dd(level: int = 0, events: int = 4) -> list[str]:
        return dd_panel(world, v, t, tr, lines, width, style, level, events, memo)

    layouts = [
        lambda: dd(events=6) + legend + notes,
        lambda: dd(events=6) + legend + notes[:1],
        lambda: dd(events=6) + legend,
        lambda: dd(events=5) + legend,
        lambda: dd() + legend,
        lambda: dd(events=3) + legend,
        lambda: dd(),
        lambda: dd(events=3),
        lambda: dd(1) + legend,
        lambda: dd(1),
        lambda: dd(2),
        lambda: dd(3),
    ]
    rest: list[str] = []
    for make in layouts:
        rest = make()
        if len(rest) <= height:
            break
    return rest[:height] + [""] * (height - len(rest))
