import shutil
from pathlib import Path

from core.contract import ROOT
from core.scaffold import rename_ids, scaffold


def test_a_new_lab_is_a_renamed_copy_of_a_working_one(tmp_path):
    for part in ("labs/caching", "live/worlds/caching.py", "live/adapters/caching.py"):
        src, dst = ROOT / part, tmp_path / part
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)
    files = scaffold("caching", "my_cache", root=tmp_path)
    names = {str(f.relative_to(tmp_path)) for f in files}
    assert {"labs/my_cache/main.py", "labs/my_cache/es/main.py", "labs/my_cache/text/en.py",
            "live/worlds/my_cache.py", "live/adapters/my_cache.py"} <= names
    world = (tmp_path / "live/worlds/my_cache.py").read_text()
    assert 'id = "my_cache"' in world and "labs.my_cache" in world and '"caching"' not in world
    assert '@adapts("my_cache"' in (tmp_path / "live/adapters/my_cache.py").read_text()


def test_ids_are_renamed_but_words_are_not():
    text = 'from labs.caching import lab\n_s = strings("caching")\n"""Lab caching: a cache in front of the db."""'
    out = rename_ids(text, "caching", "my_cache")
    assert "labs.my_cache" in out and 'strings("my_cache")' in out and "Lab my_cache:" in out
    assert "a cache in front" in out  # prose stays
