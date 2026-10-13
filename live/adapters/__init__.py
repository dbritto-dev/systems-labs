"""Adapters: each turns one lab's World into the model of one view (views/). A lab is drawn with
`World.view`; the adapter registered for (lab, view) is what feeds it.

One module per lab: live/adapters/<lab>.py, with a LaneAdapter subclass decorated with
`@adapts("<lab id>", "lanes")`. Every module here is imported, so a new file is all it takes.
"""

from __future__ import annotations

import importlib
import pkgutil

for _info in pkgutil.iter_modules(__path__):
    # Only real module names: skip "common" and copies like "cache 2.py" (Finder, iCloud).
    if _info.name != "common" and _info.name.isidentifier():
        importlib.import_module(f"{__name__}.{_info.name}")
