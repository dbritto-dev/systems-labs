"""Pictures: a View draws one kind of picture; an Adapter feeds it for one lab.

Every lab can have several pictures: one per adapter registered for it with
`@adapts("<lab>", "<view>")` (live/adapters/<lab>.py). `World.view` is the one it opens with
(lanes, unless the lab says otherwise); `views_for(world)` lists them all, so the viewer can
switch (key v, or --view).
"""

from __future__ import annotations

from live.views.base import ADAPTERS, VIEWS, Adapter, View, adapts, register  # noqa: F401
from live.views import cluster, lanes, lanes_relay  # noqa: F401  (registers the views)

_adapters: dict[tuple[int, str], Adapter] = {}


def _register_adapters() -> None:
    import live.adapters  # noqa: F401  (imports every live/adapters/<lab>.py, which registers them)


def views_for(world) -> list[str]:
    """Every picture this lab can show, the one it opens with first."""
    _register_adapters()
    names = [view for (lab, view) in ADAPTERS if lab == world.id and view in VIEWS]
    default = type(world).view
    return sorted(names, key=lambda v: (v != default, v))


def set_view(world, name: str) -> None:
    """Show `name` from now on (it must be one of views_for(world))."""
    choices = views_for(world)
    if name not in choices:
        from core.i18n import screen_text

        raise LookupError(screen_text().NO_VIEW.format(lab=world.id, name=name, views=", ".join(choices)))
    world.view = name


def next_view(world) -> str:
    """Switch to the lab's next picture, round the list; returns its name."""
    choices = views_for(world)
    if choices:
        world.view = choices[(choices.index(world.view) + 1) % len(choices)] if world.view in choices else choices[0]
    return world.view


def adapter_for(world) -> Adapter:
    _register_adapters()
    key = (id(world), world.view)
    a = _adapters.get(key)
    if a is None or a.world is not world:
        lab_view = (world.id, world.view)
        if lab_view not in ADAPTERS:
            raise LookupError(f"no adapter for lab {world.id!r} and view {world.view!r}")
        a = _adapters[key] = ADAPTERS[lab_view](world)
    return a


def render(world, canvas, variant: str, t: float) -> None:
    if world.view not in VIEWS:
        raise LookupError(f"no view named {world.view!r}")
    VIEWS[world.view].draw(canvas, adapter_for(world), variant, t)
