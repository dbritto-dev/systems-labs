import pytest

from core import testing


def test_starting_code_turns_a_failure_into_a_skip_for_you_and_stays_strict_for_the_repo(monkeypatch):
    @testing.starting_code
    def claims_the_starting_code_is_wrong():
        assert False, "main.py moved on"

    monkeypatch.setattr(testing, "REFERENCE", False)
    monkeypatch.setattr(testing, "STRICT", False)
    with pytest.raises(pytest.skip.Exception):
        claims_the_starting_code_is_wrong()
    monkeypatch.setattr(testing, "REFERENCE", True)
    with pytest.raises(AssertionError):
        claims_the_starting_code_is_wrong()
    monkeypatch.setattr(testing, "REFERENCE", False)
    monkeypatch.setattr(testing, "STRICT", True)  # the repo's checks on the untouched main.py
    with pytest.raises(AssertionError):
        claims_the_starting_code_is_wrong()


def test_starting_code_keeps_the_test_name_for_pytest():
    @testing.starting_code
    def test_something(seed):
        return seed

    assert test_something.__name__ == "test_something" and test_something(3) == 3
