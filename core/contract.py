"""Loading lab code by name, discovering labs, and checking `--set` params.

Your files are language-aware: `main` and `reference` are labs/<lab>/main.py in English and
labs/<lab>/es/main.py in Spanish (same code names, Spanish comments). Every other module
of a lab (scenario, lab, the catalogs) is shared.
"""

from __future__ import annotations

import difflib
import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from core.i18n import DEFAULT, catalog, lab_text, lang

ROOT = Path(__file__).resolve().parent.parent
LABS = ROOT / "labs"
STUDENT_FILES = ("main", "reference")  # the files that exist once per language


def _msg(key: str, /, **values: Any) -> str:
    return getattr(catalog("core.text"), key).format(**values)


def localized(lab: str, module: str) -> str:
    """The module name in the language in use: "main" -> "es.main" in Spanish (if it exists)."""
    code = lang()
    if module in STUDENT_FILES and code != DEFAULT and (LABS / lab / code / f"{module}.py").exists():
        return f"{code}.{module}"
    return module


def module_path(lab: str, module: str) -> Path:
    if module.endswith(".py"):
        return Path(module).resolve()
    return LABS / lab / (localized(lab, module).replace(".", "/") + ".py")


def import_module(lab: str, module: str) -> ModuleType:
    """Import `labs/<lab>/<module>.py` (in the language in use), or any `.py` file given by path."""
    if module.endswith(".py"):
        path = Path(module).resolve()
        if not path.exists():
            raise ImportError(_msg("DOES_NOT_EXIST", file=module), path=str(path))
        name = f"labs.{lab}._variant_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    return importlib.import_module(f"labs.{lab}.{localized(lab, module)}")


def load(lab: str, module: str, names: list[str] | tuple[str, ...]) -> SimpleNamespace:
    """Import a lab module and return the requested names.

    A missing (or misspelled) name raises an ImportError that names it and
    the file to edit.
    """
    mod = import_module(lab, module)
    path = module_path(lab, module)
    try:
        shown = path.relative_to(ROOT)
    except ValueError:
        shown = path
    missing = [n for n in names if not hasattr(mod, n)]
    if missing:
        have = [n for n in dir(mod) if not n.startswith("_")]
        parts = []
        for n in missing:
            close = difflib.get_close_matches(n, have, n=1)
            parts.append(_msg("A_TYPO", name=n, close=close[0]) if close else repr(n))
        raise ImportError(_msg("MUST_DEFINE", file=shown, names=", ".join(parts)),
                          name=missing[0], path=str(path))
    ns = SimpleNamespace(**{n: getattr(mod, n) for n in names})
    ns.__file__ = str(path)
    return ns


# ---------------------------------------------------------------- discovery


@dataclass(frozen=True, slots=True)
class Param:
    default: Any
    help: str = ""  # in the lab's catalog: PARAMS[name]


def _text_or_none(lab: str) -> ModuleType | None:
    try:
        return lab_text(lab)
    except ModuleNotFoundError:
        return None


def meta_of(lab: str) -> dict:
    """A lab's META, with its title, summary and param help in the language in use."""
    meta = dict(importlib.import_module(f"labs.{lab}.lab").META)
    text = _text_or_none(lab)
    if text is not None:
        meta["title"], meta["summary"] = text.TITLE, text.SUMMARY
        helps = getattr(text, "PARAMS", {})
        meta["params"] = {k: Param(p.default, helps.get(k, p.help)) for k, p in meta.get("params", {}).items()}
    return meta


def lesson_of(lab: str):
    """A lab's Lesson in the language in use."""
    text = _text_or_none(lab)
    if text is not None:
        return text.LESSON
    return importlib.import_module(f"labs.{lab}.lesson").LESSON


def discover() -> dict[str, dict]:
    """Every `labs/*/lab.py` exposes META. Returns {lab id: META}, sorted by id."""
    found = {}
    for lab_py in sorted(LABS.glob("*/lab.py")):
        if not lab_py.parent.name.isidentifier():
            continue  # e.g. a Finder copy "cache 2"
        mod = importlib.import_module(f"labs.{lab_py.parent.name}.lab")
        if getattr(mod, "META", None) is None:
            raise ImportError(_msg("MUST_DEFINE", file=lab_py.relative_to(ROOT), names="META"))
        found[mod.META["id"]] = meta_of(lab_py.parent.name)
    return found


def _convert(name: str, default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on", "si", "sí"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(_msg("NOT_BOOL", name=name, raw=raw))
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            raise ValueError(_msg("NOT_INT", name=name, raw=raw)) from None
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            raise ValueError(_msg("NOT_NUMBER", name=name, raw=raw)) from None
    return raw


def parse_params(meta: dict, sets: list[str] | None) -> dict[str, Any]:
    """Defaults from META, overridden by `name=value` strings. Raises ValueError."""
    spec: dict[str, Param] = meta.get("params", {})
    out = {k: p.default for k, p in spec.items()}
    for item in sets or []:
        if "=" not in item:
            raise ValueError(_msg("SET_FORMAT", item=item))
        name, raw = (s.strip() for s in item.split("=", 1))
        if name not in spec:
            known = ", ".join(spec) or _msg("NONE")
            close = difflib.get_close_matches(name, list(spec), n=1)
            hint = _msg("DID_YOU_MEAN", name=close[0]) if close else ""
            raise ValueError(_msg("UNKNOWN_PARAM", name=name, lab=meta["id"], known=known, hint=hint))
        out[name] = _convert(name, spec[name].default, raw)
    return out
