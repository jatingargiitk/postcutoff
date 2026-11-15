import pytest

from postcutoff.versions import gap, is_prerelease, release_tuple, same_release, sort_key


@pytest.mark.parametrize("v,pre", [
    ("1.2.3", False), ("2.0", False), ("1.0.post1", False), ("1.0+local", False),
    ("2.11.0b1", True), ("2.0rc1", True), ("1.0.dev3", True), ("4.0.0-beta.1", True),
    ("4.5.0-canary.20260828T171753", True), ("not-a-version", True),
])
def test_prerelease(v, pre):
    assert is_prerelease(v) is pre


def test_ordering_puts_final_after_pre():
    vs = ["2.11.0", "2.11.0b1", "2.10.6", "2.9.0", "10.0.0"]
    assert sorted(vs, key=sort_key) == ["2.9.0", "2.10.6", "2.11.0b1", "2.11.0", "10.0.0"]


def test_same_release_and_tuple():
    assert release_tuple("1!2.3") == (2, 3, 0)
    assert same_release("2.0", "2.0.0")
    assert not same_release("2.0rc1", "2.0.0")


@pytest.mark.parametrize("pinned,known,level", [
    ("2.11.3", "2.10.6", "minor"), ("4.0.5", "3.24.1", "major"), ("8.3.5", "8.3.4", "patch"),
    ("0.57.0", "0.36.3", "major"), ("0.1.5", "0.1.2", "patch"), ("weird", "1.0", "major"),
])
def test_gap(pinned, known, level):
    assert gap(pinned, known) == level
