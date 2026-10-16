"""`python -m live new <name> --like <lab>`: start a new lab as a copy of a working one (the Prototype pattern).

It copies labs/<lab>/ (both languages: main, reference, README, text catalogs, es/ files, scenario, lab, tests),
live/worlds/<lab>.py and live/adapters/<lab>.py, and renames the lab's id everywhere it is used as an id
(module paths, `"<lab>"` in code, `<lab>` in Markdown, "Lab <lab>:" in docstrings). The copy runs and passes
its tests as it is; then you change it into your lab.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.contract import ROOT

TEXT = {".py", ".md"}


def rename_ids(text: str, old: str, new: str) -> str:
    o = re.escape(old)
    text = re.sub(rf"\blabs([/.]){o}\b", rf"labs\g<1>{new}", text)  # paths and module names
    text = re.sub(rf"\b(live|adapters|worlds)([/.]){o}\b", rf"\1\2{new}", text)
    text = re.sub(rf"`{o}`", f"`{new}`", text)  # Markdown
    text = re.sub(rf"\b(python -m live|Lab|lab|Laboratorio|laboratorio|World for lab|pictures for lab) {o}\b(?!-)",
                  rf"\1 {new}", text)
    return re.sub(rf"([\"']){o}\1", rf"\g<1>{new}\g<1>", text)  # "lab" as an id in code


def scaffold(like: str, name: str, root: Path = ROOT) -> list[Path]:
    """Copy lab `like` to a new lab `name` under `root`; returns the files written."""
    if not name.isidentifier():
        raise ValueError(f"a lab name must be a Python identifier like my_lab, not {name!r}")
    src = root / "labs" / like
    if not src.is_dir():
        raise ValueError(f"no lab named {like!r} to copy")
    dst = root / "labs" / name
    if dst.exists():
        raise ValueError(f"labs/{name} already exists")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    written = [p for p in dst.rglob("*") if p.is_file()]
    for kind in ("worlds", "adapters"):
        f = root / "live" / kind / f"{like}.py"
        if f.exists():
            target = root / "live" / kind / f"{name}.py"
            shutil.copy(f, target)
            written.append(target)
    for p in written:
        if p.suffix in TEXT:
            p.write_text(rename_ids(p.read_text(), like, name))
    return sorted(written)
