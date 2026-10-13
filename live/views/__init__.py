"""Pick the view a World asks for and the adapter for (lab, view)."""

from __future__ import annotations

from live.views.base import ADAPTERS, VIEWS, Adapter, View, adapts, register  # noqa: F401
from live.views import lanes  # noqa: F401  (registers the lanes view)

_adapters: dict[int, Adapter] = {}


def adapter_for(world) -> Adapter:
    import live.adapters  # noqa: F401  (registers the lab adapters)

    a = _adapters.get(id(world))
    if a is None or a.world is not world:
        key = (world.id, world.view)
        if key not in ADAPTERS:
            raise LookupError(f"no adapter for lab {world.id!r} and view {world.view!r}")
        a = _adapters[id(world)] = ADAPTERS[key](world)
    return a


def render(world, canvas, variant: str, t: float) -> None:
    if world.view not in VIEWS:
        raise LookupError(f"no view named {world.view!r}")
    VIEWS[world.view].draw(canvas, adapter_for(world), variant, t)
