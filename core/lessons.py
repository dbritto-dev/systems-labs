"""What a lab teaches: the concept, what to watch for, and where to read more."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Ref:
    title: str
    url: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Lesson:
    title: str
    one_liner: str
    learn: tuple[str, ...]
    watch_for: tuple[str, ...]
    build: tuple[tuple[str, str], ...]  # (caption, production snippet)
    checklist: tuple[str, ...]
    refs: tuple[Ref, ...]
    try_next: tuple[str, ...] = field(default_factory=tuple)
