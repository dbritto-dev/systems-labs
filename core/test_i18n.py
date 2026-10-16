"""Every language has every word: same names, keys, lengths and {placeholders}."""

import ast
import importlib
from pathlib import Path

import pytest

from core import i18n
from core.contract import LABS

LAB_IDS = sorted(p.parent.name for p in LABS.glob("*/lab.py") if p.parent.name.isidentifier())
TRANSLATED = [lab for lab in LAB_IDS if (LABS / lab / "text" / "en.py").exists()]


def both(package: str):
    return [i18n.catalog(package, code) for code in i18n.LANGS]


@pytest.mark.parametrize("package", ["live.text", "core.text"])
def test_screen_and_core_catalogs_match(package):
    en, *others = both(package)
    for other in others:
        assert i18n.check(en, other) == []


@pytest.mark.parametrize("lab", TRANSLATED)
def test_lab_catalogs_match(lab):
    en, *others = both(f"labs.{lab}.text")
    for other in others:
        assert i18n.check(en, other) == [], other.__name__


@pytest.mark.parametrize("lab", TRANSLATED)
@pytest.mark.parametrize("code", i18n.LANGS)
def test_lab_words_fit_the_screen(lab, code):
    text = i18n.lab_text(lab, code)
    for s in text.STAGES:
        assert len(s.story) <= 90, s.story
    for key, g in text.GOALS.items():
        assert len(g.fix) <= 28, (key, g.fix)
    for verb in getattr(text, "VERBS", {}).values():
        assert len(verb) <= 6, verb


def public_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return {n for n in names if not n.startswith("_")}


@pytest.mark.parametrize("lab", TRANSLATED)
@pytest.mark.parametrize("module", ["main", "reference"])
def test_spanish_student_files_have_the_same_names(lab, module):
    en, es = LABS / lab / f"{module}.py", LABS / lab / "es" / f"{module}.py"
    assert es.exists(), f"{es} is missing"
    needed = set(importlib.import_module(f"labs.{lab}.scenario").NAMES)
    assert needed <= public_names(es), needed - public_names(es)
    assert public_names(en) == public_names(es)


def test_the_language_comes_from_the_environment(monkeypatch):
    monkeypatch.setattr(i18n, "_lang", None)
    monkeypatch.setenv("LABS_LANG", "es")
    assert i18n.lang() == "es"
    monkeypatch.setenv("LABS_LANG", "xx")
    assert i18n.lang() == "en"
    with pytest.raises(ValueError):
        i18n.set_lang("xx")


def test_check_finds_every_kind_of_difference():
    import types

    a, b = types.ModuleType("a"), types.ModuleType("b")
    a.X, b.X = {"k": "hello {name}", "only_a": "x"}, {"k": "hola {nombre}"}
    a.Y, b.Y = [1, 2], [1]
    a.Z = "z"
    problems = "\n".join(i18n.check(a, b))
    assert "placeholders" in problems and "only_a" in problems and "2 items" in problems and "Z" in problems


def test_every_lab_speaks_every_language():
    missing = [f"{lab}/text/{code}.py" for lab in LAB_IDS for code in i18n.LANGS
               if not (LABS / lab / "text" / f"{code}.py").exists()]
    missing += [f"{lab}/es/{m}" for lab in LAB_IDS for m in ("main.py", "reference.py", "README.md")
                if not (LABS / lab / "es" / m).exists()]
    assert missing == []


@pytest.mark.parametrize("lab", LAB_IDS)
def test_every_goal_phase_and_legend_key_has_words(lab):
    from live.worlds import make_world

    world = make_world(lab)
    for code in i18n.LANGS:
        phases = i18n.screen_text(code).PHASES
        assert {g.phase for g in world.goals} <= phases.keys()
    names = getattr(world.text, "LEGEND", {})
    for item in type(world).legend:
        assert item[1] in names, f"{lab}: legend key {item[1]!r} is not in LEGEND"
    for g in type(world).goals:
        assert g.key in world.text.GOALS, f"{lab}: goal key {g.key!r} is not in GOALS"


def test_bar_labels_leave_a_gap_before_their_bar():
    """The panel gives a bar's label 10 columns; at 10 letters it would touch the bar."""
    from core.contract import discover
    from core.i18n import LANGS, catalog

    long = [(lab, code, k, v) for lab in discover() for code in LANGS
            for k, v in getattr(catalog(f"labs.{lab}.text", code), "STRINGS", {}).items()
            if k.startswith("bar_") and "{" not in v and len(v) > 9]
    assert not long, long
