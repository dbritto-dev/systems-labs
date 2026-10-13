"""The screen tests read English words: pin the language for each module, whatever LABS_LANG says."""

import os

import pytest

from core import i18n


@pytest.fixture(autouse=True, scope="module")
def english():
    saved = i18n._lang, os.environ.get("LABS_LANG")
    i18n._lang = "en"
    os.environ["LABS_LANG"] = "en"
    yield
    i18n._lang = saved[0]
    if saved[1] is None:
        os.environ.pop("LABS_LANG", None)
    else:
        os.environ["LABS_LANG"] = saved[1]
