"""uv run python -m live [lab] [--at SECONDS] [--size WxH] [--color] [--set name=value]

With no lab, list the labs. With a lab, watch it live: edit
labs/<lab>/main.py and save, and this window reruns it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from core.contract import ROOT, discover, parse_params
from live.canvas import BLUE, EXTRA2, MUTED, RED, Style
from live.frame import compose, spinner
from live.runner import Feed
from live.worlds import make_world

SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
SEEK = 5.0
STATUS_SECONDS = 4.0


def list_labs() -> int:
    labs = discover()
    print("Labs (watch one with: uv run python -m live <lab>)\n")
    width = max(len(k) for k in labs) if labs else 0
    for lab_id, meta in labs.items():
        print(f"  {lab_id:<{width}}  {meta['summary']}")
    print()
    return 0


def print_lesson(lab: str) -> int:
    import importlib
    import textwrap

    lesson = importlib.import_module(f"labs.{lab}.lesson").LESSON

    def para(s: str, indent: str = "  ") -> str:
        return textwrap.fill(s, 88, initial_indent=indent, subsequent_indent=indent + "  ")

    out = [lesson.title, lesson.one_liner, "", "Learn"]
    out += [para("- " + s) for s in lesson.learn]
    out += ["", "Watch for"] + [para("- " + s) for s in lesson.watch_for]
    out += ["", "In production"]
    for caption, snippet in lesson.build:
        out += [f"  {caption}:"] + [f"      {line}" for line in snippet.splitlines()] + [""]
    out += ["Checklist"] + [para("[ ] " + s) for s in lesson.checklist]
    out += ["", "Read more"]
    for ref in lesson.refs:
        out += [f"  - {ref.title}", f"    {ref.url}"] + ([para(ref.note, "    ")] if ref.note else [])
    out += ["", "Try next"] + [para("- " + s) for s in lesson.try_next]
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
    lines = compose(world, feed.variant, t, cols, rows, style=style, mode="paused", error=feed.error)
    sys.stdout.write("\n".join(lines) + "\n")
    return 1 if feed.error else 0


def mtimes(lab: str) -> dict[str, float]:
    out = {}
    for p in (ROOT / "labs" / lab).glob("*.py"):
        try:
            out[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return out


def watch(world, feed: Feed, lab: str, args) -> int:
    from live.screen import Terminal

    style = Style(colour_mode(args.color))
    t, speed_i, paused = 0.0, SPEEDS.index(1.0), False
    status: tuple[str, tuple] | None = ("running your code…", MUTED)
    status_until = float("inf")
    reason = ""
    seen = mtimes(lab)
    next_poll = 0.0
    feed.restart()
    last = time.monotonic()
    with Terminal() as term:
        while True:
            now = time.monotonic()
            dt, last = now - last, now
            feed.tick(t)
            if feed.restarted:
                feed.restarted = False
                t = 0.0
                if reason:
                    status = (f"{reason} at {datetime.now():%H:%M:%S}: playing from 0:00", BLUE)
                else:
                    status = None
                status_until = now + STATUS_SECONDS
            if feed.error:
                status, status_until = (f"error: {feed.error}", RED), float("inf")
            run = world.runs.get(feed.variant)
            mode = "play"
            if run is not None and not paused:
                t += dt * SPEEDS[speed_i]
                if t >= run.end - 0.05:
                    t = max(0.0, run.end - 0.05)
                    mode = "simulating"
            if paused:
                mode = "paused"
            elif run is None:
                mode = "simulating"
            if status and now > status_until:
                status = None
            if now >= next_poll:
                next_poll = now + 0.5
                current = mtimes(lab)
                if current != seen:
                    seen = current
                    reason = "reran"
                    feed.restart()
                    status, status_until = ("running your code…", EXTRA2), float("inf")
            cols, rows = term.size()
            loading = feed.loading
            shown = status
            if loading and run is not None and not feed.error:  # a rerun: the old picture stays meanwhile
                step, waited = loading
                what = "loading your code" if step == "starting" else "simulating the first minute"
                shown = (f"{spinner(waited)} {what}… {waited:.1f}s", EXTRA2)
            lines = compose(world, feed.variant, t, cols, rows, style=style, mode=mode, speed=SPEEDS[speed_i],
                            status=shown, error=feed.error, loading=loading)
            term.show(lines)
            for key in term.keys(0.05):
                match key:
                    case "q" | "esc" | "ctrl-c":
                        return 0
                    case "space":
                        paused = not paused
                    case "0" if run is not None and run.earliest == 0:
                        t = 0.0
                    case "0" | "r":
                        reason = "reran" if key == "r" else "restarted"
                        feed.restart()
                        status, status_until = ("running your code…", EXTRA2), float("inf")
                    case "left" | "right" if run is not None:
                        step = SEEK if key == "right" else -SEEK
                        t = min(max(run.earliest, t + step), max(0.0, run.end - 0.05))
                    case "up":
                        speed_i = min(len(SPEEDS) - 1, speed_i + 1)
                    case "down":
                        speed_i = max(0, speed_i - 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m live", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lab", nargs="?", help="the lab to watch (omit to list labs)")
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

    labs = discover()
    if not args.lab:
        return list_labs()
    if args.lab not in labs:
        print(f"no lab named {args.lab!r}. Labs: {', '.join(labs)}", file=sys.stderr)
        return 2
    try:
        params = parse_params(labs[args.lab], args.set)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.lesson:
        return print_lesson(args.lab)
    variant = args.variant
    if variant.endswith(".py"):
        variant = str(Path(variant).resolve())
    world = make_world(args.lab, params)
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
