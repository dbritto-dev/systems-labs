"""Views draw a picture; adapters turn one lab's World into what a view needs.

A View knows nothing about labs. An Adapter knows one lab and one view.
Register them with `@register` and `@adapts(lab_id, view_name)`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

VIEWS: dict[str, "View"] = {}
ADAPTERS: dict[tuple[str, str], type["Adapter"]] = {}


class View(ABC):
    name: str = ""

    @abstractmethod
    def draw(self, cv, adapter: "Adapter", variant: str, t: float) -> None:
        """Draw the picture for time t onto the canvas."""


class Adapter(ABC):
    def __init__(self, world) -> None:
        self.world = world


def register(cls: type[View]) -> type[View]:
    VIEWS[cls.name] = cls()
    return cls


def adapts(lab_id: str, view_name: str):
    def deco(cls: type[Adapter]) -> type[Adapter]:
        ADAPTERS[(lab_id, view_name)] = cls
        return cls

    return deco
