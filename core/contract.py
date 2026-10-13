"""Loading lab code by name, discovering labs, and checking `--set` params."""

from __future__ import annotations

import difflib
import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LABS = ROOT / "labs"


def module_path(lab: str, module: str) -> Path:
    if module.endswith(".py"):
        return Path(module).resolve()
    return LABS / lab / f"{module}.py"


def import_module(lab: str, module: str) -> ModuleType:
    """Import `labs/<lab>/<module>.py`, or any `.py` file given by path."""
    if module.endswith(".py"):
        path = Path(module).resolve()
        if not path.exists():
            raise ImportError(f"{module} does not exist", path=str(path))
        name = f"labs.{lab}._variant_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    return importlib.import_module(f"labs.{lab}.{module}")


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
            parts.append(f"{n!r}" + (f" (found {close[0]!r}: a typo?)" if close else ""))
        raise ImportError(
            f"{shown} must define {', '.join(parts)}", name=missing[0], path=str(path)
        )
    ns = SimpleNamespace(**{n: getattr(mod, n) for n in names})
    ns.__file__ = str(path)
    return ns


# ---------------------------------------------------------------- discovery


@dataclass(frozen=True, slots=True)
class Param:
    default: Any
    help: str


def discover() -> dict[str, dict]:
    """Every `labs/*/lab.py` exposes META. Returns {lab id: META}, sorted by id."""
    found = {}
    for lab_py in sorted(LABS.glob("*/lab.py")):
        mod = importlib.import_module(f"labs.{lab_py.parent.name}.lab")
        meta = getattr(mod, "META", None)
        if meta is None:
            raise ImportError(f"{lab_py.relative_to(ROOT)} must define META")
        found[meta["id"]] = meta
    return found


def _convert(name: str, default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{name} must be true or false, got {raw!r}")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"{name} must be a number, got {raw!r}") from None
    return raw


def parse_params(meta: dict, sets: list[str] | None) -> dict[str, Any]:
    """Defaults from META, overridden by `name=value` strings. Raises ValueError."""
    spec: dict[str, Param] = meta.get("params", {})
    out = {k: p.default for k, p in spec.items()}
    for item in sets or []:
        if "=" not in item:
            raise ValueError(f"--set expects name=value, got {item!r}")
        name, raw = (s.strip() for s in item.split("=", 1))
        if name not in spec:
            known = ", ".join(spec) or "none"
            close = difflib.get_close_matches(name, list(spec), n=1)
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise ValueError(f"unknown param {name!r} for {meta['id']} (known: {known}).{hint}")
        out[name] = _convert(name, spec[name].default, raw)
    return out
