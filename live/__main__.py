"""uv run python -m live [lab] [--lang en|es] [--view NAME] [--at SECONDS] [--size WxH] [--color]
                     [--set name=value] [--variant main|reference|FILE.py] [--seed N] [--lesson]

With no lab, list the labs. With a lab, watch it live: edit labs/<lab>/main.py (in Spanish,
labs/<lab>/es/main.py) and save, and this window reruns it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from core.contract import discover, lesson_of, parse_params
from core.i18n import LANGS, screen_text, set_lang
from live.canvas import Style
from live.frame import compose
from live.runner import Feed
from live.views import set_view, views_for
from live.viewer import Viewer
from live.worlds import make_world



def list_labs() -> int:
    labs = discover()
    print(screen_text().LABS_HEADER + "\n")
    width = max(len(k) for k in labs) if labs else 0
    for lab_id, meta in labs.items():
        print(f"  {lab_id:<{width}}  {meta['summary']}")
    print()
    return 0


def print_lesson(lab: str) -> int:
    import textwrap

    lesson = lesson_of(lab)
    heads = screen_text().LESSON

    def para(s: str, indent: str = "  ") -> str:
        return textwrap.fill(s, 88, initial_indent=indent, subsequent_indent=indent + "  ")

    out = [lesson.title, lesson.one_liner, "", heads["learn"]]
    out += [para("- " + s) for s in lesson.learn]
    out += ["", heads["watch"]] + [para("- " + s) for s in lesson.watch_for]
    out += ["", heads["build"]]
    for caption, snippet in lesson.build:
        out += [f"  {caption}:"] + [f"      {line}" for line in snippet.splitlines()] + [""]
    out += [heads["checklist"]] + [para("[ ] " + s) for s in lesson.checklist]
    out += ["", heads["refs"]]
    for ref in lesson.refs:
        out += [f"  - {ref.title}", f"    {ref.url}"] + ([para(ref.note, "    ")] if ref.note else [])
    out += ["", heads["next"]] + [para("- " + s) for s in lesson.try_next]
    print("\n".join(out))
    return 0


def colour_mode(forced: bool) -> str:
    if os.environ.get("NO_COLOR"):
        return "none"
    if forced or os.environ.get("COLORTERM", "") in ("truecolor", "24bit"):
        return "true"
    return "256"


def parse_size(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise SystemExit(f"--size expects WIDTHxHEIGHT like 110x44, got {s!r}") from None


def one_frame(world, feed: Feed, lab: str, args) -> int:
    cols, rows = parse_size(args.size) if args.size else (110, 44)
    feed.build_until(args.at)
    feed.close()
    run = world.runs.get(feed.variant)
    t = min(args.at, run.end) if run else 0.0
    style = Style("true" if args.color else "none")
    lines = compose(world, feed.variant, t, cols, rows, style=style, mode="paused", error=feed.error,
                    views=len(views_for(world)))
    sys.stdout.write("\n".join(lines) + "\n")
    return 1 if feed.error else 0


FRAME = 1 / 30  # seconds between frames: a steady pace, whatever each frame cost


def watch(world, feed: Feed, lab: str, args) -> int:
    """The game loop: at a steady FRAME pace, update and draw a frame (only when it changed); between frames,
    wait for keys, and draw at once after one so the window answers immediately."""
    from live.screen import Terminal

    viewer = Viewer(world, feed, lab, Style(colour_mode(args.color)))
    with Terminal() as term:
        next_at = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= next_at:
                lines = viewer.frame(now, *term.size())
                if lines is not None:
                    term.show(lines)
                next_at = max(next_at + FRAME, now)  # keep the pace; never rush to catch up
            keys = term.keys(max(0.0, next_at - time.monotonic()))
            for key in keys:
                if not viewer.handle(key, time.monotonic()):
                    return 0
            if keys:
                next_at = time.monotonic()  # a key: show its effect now


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m live", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lab", nargs="?", help="the lab to watch (omit to list labs)")
    ap.add_argument("--lang", choices=LANGS, help="language: en (default) or es; or set LABS_LANG")
    ap.add_argument("--view", help="the picture to show (default: the lab's own; key v switches)")
    ap.add_argument("--at", type=float, help="print one frame at this many seconds and exit")
    ap.add_argument("--size", help="frame size for --at, like 110x44")
    ap.add_argument("--color", action="store_true", help="use 24-bit colour")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="change a lab parameter")
    ap.add_argument("--variant", default="main",
                    help="main (your file), reference, or a path to a .py file")
    ap.add_argument("--seed", type=int, default=1, help="random seed for incidents")
    ap.add_argument("--lesson", action="store_true", help="print the lab's lesson and exit")
    args = ap.parse_args(argv)
    if args.lang:
        set_lang(args.lang)  # before anything reads a catalog; child processes inherit it

    labs = discover()
    if not args.lab:
        return list_labs()
    if args.lab not in labs:
        print(screen_text().NO_LAB.format(name=args.lab, labs=", ".join(labs)), file=sys.stderr)
        return 2
    try:
        params = parse_params(labs[args.lab], args.set)
    except ValueError as e:
        print(screen_text().ERROR.format(error=e), file=sys.stderr)
        return 2
    if args.lesson:
        return print_lesson(args.lab)
    variant = args.variant
    if variant.endswith(".py"):
        variant = str(Path(variant).resolve())
    world = make_world(args.lab, params)
    if args.view:
        try:
            set_view(world, args.view)
        except LookupError as e:
            print(screen_text().ERROR.format(error=e), file=sys.stderr)
            return 2
    feed = Feed(world, args.lab, variant, seed=args.seed)
    if args.at is not None:
        return one_frame(world, feed, args.lab, args)
    try:
        return watch(world, feed, args.lab, args)
    except KeyboardInterrupt:
        return 0
    finally:
        feed.close()


if __name__ == "__main__":
    sys.exit(main())
