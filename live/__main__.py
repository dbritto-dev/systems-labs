"""uv run python -m live [lab] [--lang en|es] [--view NAME] [--at SECONDS] [--size WxH] [--color]
                     [--set name=value] [--variant main|reference|FILE.py] [--seed N] [--lesson]
                     [--record FILE] [--replay FILE]

With no lab, list the labs. With a lab, watch it live: edit labs/<lab>/main.py (in Spanish,
labs/<lab>/es/main.py) and save, and this window reruns it.
"""

from __future__ import annotations

import argparse
import json
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
        w, h = int(w), int(h)
    except ValueError:
        raise SystemExit(f"--size expects WIDTHxHEIGHT like 110x44, got {s!r}") from None
    if w <= 0 or h <= 0:
        raise SystemExit(f"--size expects a positive WIDTHxHEIGHT like 110x44, got {s!r}")
    return w, h


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
BUDGET = 0.6  # of FRAME: when composing costs more than this, frames come less often (input stays quick)


def watch(world, feed: Feed, lab: str, args) -> int:
    """The game loop: at a steady FRAME pace, update and draw a frame (only when it changed); between frames,
    wait for keys, and draw at once after one so the window answers immediately. With --record FILE every key
    is written down with its time; with --replay FILE those keys are pressed again at those times."""
    from live.screen import Terminal

    viewer = Viewer(world, feed, lab, Style(colour_mode(args.color)))
    record = open(args.record, "w") if args.record else None
    script = load_keys(args.replay) if args.replay else []
    start = time.monotonic()
    try:
        with Terminal() as term:
            next_at = start
            while True:
                now = time.monotonic()
                if now >= next_at:
                    lines = viewer.frame(now, *term.size())
                    if lines is not None:
                        term.show(lines)
                    cost = time.monotonic() - now
                    # keep the pace, never rush to catch up; and when frames get expensive (a huge terminal, a slow
                    # machine), draw less often rather than let the keys wait (a frame budget)
                    next_at = max(next_at + max(FRAME, cost / BUDGET), now)
                keys = term.keys(max(0.0, min(next_at, script[0][0] + start if script else next_at) - time.monotonic()))
                while script and time.monotonic() - start >= script[0][0]:
                    keys.append(script.pop(0)[1])
                for key in keys:
                    if record is not None:
                        record.write(json.dumps({"t": round(time.monotonic() - start, 3), "key": key}) + "\n")
                        record.flush()
                    if not viewer.handle(key, time.monotonic()):
                        return 0
                if keys:
                    next_at = time.monotonic()  # a key: show its effect now
    finally:
        if record is not None:
            record.close()


def load_keys(path: str) -> list[tuple[float, str]]:
    """A --record file: one {"t": seconds since the start, "key": name} per line, in order."""
    out = []
    with open(path) as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                out.append((float(e["t"]), str(e["key"])))
    return sorted(out)


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
    ap.add_argument("--record", metavar="FILE", help="write every key you press, with its time, to FILE")
    ap.add_argument("--replay", metavar="FILE", help="press the keys recorded in FILE again, at their times")
    args = ap.parse_args(argv)
    if args.lang:
        set_lang(args.lang)  # before anything reads a catalog; child processes inherit it

    labs = discover()
    if not args.lab:
        return list_labs()
    if args.lab not in labs:
        import difflib

        close = difflib.get_close_matches(args.lab, list(labs), n=1)
        hint = screen_text().DID_YOU_MEAN.format(name=close[0]) if close else ""
        print(screen_text().NO_LAB.format(name=args.lab, labs=", ".join(labs)) + hint, file=sys.stderr)
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
