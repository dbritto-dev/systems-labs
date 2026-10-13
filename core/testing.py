"""Test helpers shared by the labs.

Tests of code you still have to write are marked xfail: they show up as
`x` (not yet) or `X` (done!) and never as failures. With LABS_REFERENCE=1
the same tests run against `reference.py` and must pass.
"""

from __future__ import annotations

import os

import pytest

REFERENCE = os.environ.get("LABS_REFERENCE", "") not in ("", "0")


def variant() -> str:
    """The module your-code tests target: `main`, or `reference` with LABS_REFERENCE=1."""
    return "reference" if REFERENCE else "main"


def your_code(stage: int, what: str):
    """Mark a test of stage `stage` of main.py: xfail until you build it."""
    return pytest.mark.xfail(
        not REFERENCE, reason=f"stage {stage} of main.py: {what}", strict=False
    )


def build_world(lab: str, variant, minutes: int, params: dict | None = None, seed: int = 1):
    """Simulate the first `minutes` of a run in-process and return the World holding them."""
    import itertools

    from live.worlds import make_world

    world = make_world(lab, params)
    world.start(variant)
    scenario = __import__(f"labs.{lab}.scenario", fromlist=["stream"])
    pieces = scenario.stream(variant, seed=seed, **world.params)
    for piece in itertools.islice(pieces, minutes):
        world.append(variant, piece)
    pieces.close()
    return world
