"""Just enough version parsing to order releases and compare majors/minors.

Handles PEP 440 style (1.2.3, 2.0rc1, 1.0.post1, 1!2.0) and semver
(1.2.3-beta.1). Anything that isn't a plain release is a pre-release.
"""
from __future__ import annotations

import re
from typing import Tuple

_NUM = re.compile(r"^(?:\d+!)?v?(\d+(?:\.\d+)*)(.*)$")


def release_tuple(version: str) -> Tuple[int, ...]:
    m = _NUM.match(version.strip())
    if not m:
        return ()
    parts = tuple(int(p) for p in m.group(1).split("."))
    while len(parts) < 3:
        parts += (0,)
    return parts


def is_prerelease(version: str) -> bool:
    m = _NUM.match(version.strip())
    if not m:
        return True
    rest = m.group(2).lower()
    if not rest:
        return False
    # post releases and local versions are still final releases
    if re.match(r"^(\.?post\d*|-\d+|\+.*)$", rest):
        return False
    return True


def sort_key(version: str) -> tuple:
    # final releases sort after pre-releases of the same number
    return (release_tuple(version), 0 if is_prerelease(version) else 1, version)


def same_release(a: str, b: str) -> bool:
    """True if two spellings name the same release (2.0 == 2.0.0)."""
    if a == b:
        return True
    return (
        release_tuple(a) != ()
        and release_tuple(a) == release_tuple(b)
        and is_prerelease(a) == is_prerelease(b)
        and not is_prerelease(a)
    )


def gap(pinned: str, known: str) -> str:
    """How far `pinned` is ahead of `known`: major, minor or patch."""
    p, k = release_tuple(pinned), release_tuple(known)
    if not p or not k:
        return "major"
    if p[0] != k[0]:
        return "major"
    # 0.x: a minor bump is a breaking bump under semver
    if p[0] == 0 and p[1] != k[1]:
        return "major"
    if p[1] != k[1]:
        return "minor"
    return "patch"
