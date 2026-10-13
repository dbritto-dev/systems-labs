"""One World subclass per lab, in `live/worlds/<lab>.py`, exported as `WORLD`."""

from __future__ import annotations

import importlib

from live.worlds.base import World


def make_world(lab: str, params: dict | None = None) -> World:
    from core.contract import discover, parse_params

    mod = importlib.import_module(f"live.worlds.{lab}")
    if params is None:
        params = parse_params(discover()[lab], [])
    return mod.WORLD(params)
