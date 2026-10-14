"""Languages: every word on screen comes from a catalog, so a lab runs in English or Spanish.

A catalog is a plain Python module, one per language, with the same names in each:

    live/text/en.py, live/text/es.py              the screen (menus, panel titles, ...)
    labs/<lab>/text/en.py, labs/<lab>/text/es.py  one lab (stages, goals, causes, lesson, ...)

Strings may hold `{placeholders}` filled with str.format; every language must use the same
ones. `check(a, b)` lists every difference between two catalogs (a test runs it for all).

The language is `--lang` on the command line, else the LABS_LANG environment variable,
else English. The simulation never depends on it: traces hold keys (a cause is
"bad_deploy"), and only the screen turns them into words.
"""

from __future__ import annotations

import importlib
import os
import string
from dataclasses import dataclass, fields, is_dataclass
from types import ModuleType
from typing import Any

LANGS = ("en", "es")
DEFAULT = "en"
NAMES = {"en": "English", "es": "Español"}

_lang: str | None = None


def lang() -> str:
    """The language in use: set_lang(), else LABS_LANG, else English."""
    if _lang is not None:
        return _lang
    env = os.environ.get("LABS_LANG", "").strip().lower()
    return env if env in LANGS else DEFAULT


def set_lang(code: str) -> None:
    code = code.strip().lower()
    if code not in LANGS:
        raise ValueError(f"language must be one of {', '.join(LANGS)}, not {code!r}")
    global _lang
    _lang = code
    os.environ["LABS_LANG"] = code  # child processes (the simulation) see it too


def catalog(package: str, code: str | None = None) -> ModuleType:
    """The catalog module `<package>.<lang>`, e.g. catalog("labs.caching.text")."""
    return importlib.import_module(f"{package}.{code or lang()}")


def lab_text(lab: str, code: str | None = None) -> ModuleType:
    return catalog(f"labs.{lab}.text", code)


def screen_text(code: str | None = None) -> ModuleType:
    return catalog("live.text", code)


def strings(lab: str):
    """A formatter for one lab's STRINGS in the language in use: `_s = strings("caching")`,
    then `_s("few")` or `_s("avg", value=1.2)`. Looked up on every call, so it follows --lang."""

    def s(key: str, /, **values: Any) -> str:
        return lab_text(lab).STRINGS[key].format(**values)

    return s


# ---------------------------------------------------------------- shapes shared by lab catalogs


@dataclass(frozen=True, slots=True)
class StageText:
    label: str
    story: str  # "Challenge: ..." or "Solved: ...", at most 90 characters
    next: str  # the next step


@dataclass(frozen=True, slots=True)
class IncidentText:
    """How a lab's incidents are named. Whole phrases, so each language keeps its articles."""

    name: str  # in titles: "Outage" -> "Outage #3"
    the: str  # "the outage" / "la caída"
    next: str  # "the next outage" / "la próxima caída"


@dataclass(frozen=True, slots=True)
class GoalText:
    rule: str  # short: it sits in a 39-column panel
    fix: str = ""  # at most 28 characters (verbs in VERBS: at most 6)


# ---------------------------------------------------------------- parity between languages


def _fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f is not None}


def _walk(a: Any, b: Any, path: str, out: list[str]) -> None:
    if is_dataclass(a) and not isinstance(a, type):
        if type(a) is not type(b):
            out.append(f"{path}: {type(a).__name__} vs {type(b).__name__}")
            return
        for f in fields(a):
            _walk(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}", out)
    elif isinstance(a, dict):
        if not isinstance(b, dict):
            out.append(f"{path}: dict vs {type(b).__name__}")
            return
        for k in a.keys() - b.keys():
            out.append(f"{path}[{k!r}]: missing in the second catalog")
        for k in b.keys() - a.keys():
            out.append(f"{path}[{k!r}]: missing in the first catalog")
        for k in a.keys() & b.keys():
            _walk(a[k], b[k], f"{path}[{k!r}]", out)
    elif isinstance(a, (list, tuple)):
        if not isinstance(b, (list, tuple)) or len(a) != len(b):
            out.append(f"{path}: {len(a)} items vs {len(b) if isinstance(b, (list, tuple)) else type(b).__name__}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, f"{path}[{i}]", out)
    elif isinstance(a, str):
        if not isinstance(b, str):
            out.append(f"{path}: str vs {type(b).__name__}")
        elif _fields(a) != _fields(b):
            out.append(f"{path}: placeholders {sorted(_fields(a))} vs {sorted(_fields(b))}")
    elif type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        out.append(f"{path}: {type(a).__name__} vs {type(b).__name__}")


def check(first: ModuleType, second: ModuleType) -> list[str]:
    """Every difference in shape between two catalogs: names, keys, lengths, placeholders."""
    out: list[str] = []
    names_a = {n for n in vars(first) if n.isupper()}
    names_b = {n for n in vars(second) if n.isupper()}
    for n in sorted(names_a - names_b):
        out.append(f"{n}: missing in {second.__name__}")
    for n in sorted(names_b - names_a):
        out.append(f"{n}: missing in {first.__name__}")
    for n in sorted(names_a & names_b):
        _walk(getattr(first, n), getattr(second, n), n, out)
    return out
