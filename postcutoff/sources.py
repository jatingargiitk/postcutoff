"""Discover pinned dependencies in a project directory.

Supported inputs (all optional, all read-only):

* ``requirements*.txt`` - ``name==version`` lines
* ``uv.lock`` - the direct dependencies of the root (editable/virtual) package
* ``package-lock.json`` (lockfileVersion 2/3) - the root package's direct deps
* ``package.json`` without a lockfile - the floor of each version range
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Dep:
    ecosystem: str  # "pypi" or "npm"
    name: str
    version: str
    source: str  # file the version came from
    exact: bool = True  # False when the version is a range floor


@dataclass
class Skipped:
    name: str
    source: str
    reason: str


_REQ_LINE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*==\s*([A-Za-z0-9.+!_-]+)\s*(;.*)?$"
)
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize_pypi(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: str, rel: str) -> tuple:
    deps: List[Dep] = []
    skipped: List[Skipped] = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split(" #", 1)[0].strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if "://" in line or line.startswith((".", "/")):
                continue
            m = _REQ_LINE.match(line)
            if m:
                deps.append(Dep("pypi", normalize_pypi(m.group(1)), m.group(3), rel))
                continue
            n = _REQ_NAME.match(line)
            if n:
                skipped.append(Skipped(normalize_pypi(n.group(1)), rel, "not pinned with =="))
    return deps, skipped


def _toml_blocks(text: str, header: str) -> List[str]:
    parts = re.split(r"^\[\[" + re.escape(header) + r"\]\]\s*$", text, flags=re.M)
    return parts[1:]


def _toml_str(block: str, key: str) -> Optional[str]:
    m = re.search(r"^" + re.escape(key) + r'\s*=\s*"([^"]*)"', block, flags=re.M)
    return m.group(1) if m else None


def parse_uv_lock(path: str, rel: str) -> tuple:
    """Return the direct deps of the root package(s) in a uv.lock.

    uv.lock is TOML; Python 3.9/3.10 have no tomllib, so this reads the small,
    regular subset uv writes instead of pulling in a TOML dependency.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    versions: Dict[str, str] = {}
    roots: List[str] = []
    for block in _toml_blocks(text, "package"):
        name = _toml_str(block, "name")
        version = _toml_str(block, "version")
        if not name:
            continue
        name = normalize_pypi(name)
        src = re.search(r"^source\s*=\s*\{([^}]*)\}", block, flags=re.M)
        if src and ("editable" in src.group(1) or "virtual" in src.group(1)):
            roots.append(block)
            continue
        if version:
            versions[name] = version
    direct: List[str] = []
    for block in roots:
        for key in ("dependencies", "dev-dependencies"):
            # dependencies = [ { name = "x" }, ... ]   (possibly multi-line)
            m = re.search(r"^" + key + r"\s*=\s*\[(.*?)^\]", block, flags=re.M | re.S)
            if not m:
                m = re.search(r"^" + key + r"\s*=\s*\[(.*?)\]\s*$", block, flags=re.M)
            if m:
                direct += re.findall(r'name\s*=\s*"([^"]+)"', m.group(1))
        # [package.dev-dependencies] / [package.optional-dependencies] tables:
        #   group = [ { name = "x" }, ... ]
        for table in ("dev-dependencies", "optional-dependencies"):
            sub = re.search(
                r"^\[package\." + table + r"\]\s*$(.*?)(?=^\[|\Z)", block, flags=re.M | re.S
            )
            if sub:
                direct += re.findall(r'name\s*=\s*"([^"]+)"', sub.group(1))
    deps: List[Dep] = []
    skipped: List[Skipped] = []
    seen = set()
    for raw in direct:
        name = normalize_pypi(raw)
        if name in seen:
            continue
        seen.add(name)
        if name in versions:
            deps.append(Dep("pypi", name, versions[name], rel))
        else:
            skipped.append(Skipped(name, rel, "no version in uv.lock"))
    return deps, skipped


def _npm_direct_names(manifest: dict) -> List[str]:
    names: List[str] = []
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        for name in (manifest.get(key) or {}):
            if name not in names:
                names.append(name)
    return names


def parse_package_lock(path: str, rel: str) -> tuple:
    with open(path, encoding="utf-8") as fh:
        lock = json.load(fh)
    packages = lock.get("packages")
    deps: List[Dep] = []
    skipped: List[Skipped] = []
    if not isinstance(packages, dict):
        skipped.append(Skipped("*", rel, "lockfileVersion 1 is not supported"))
        return deps, skipped
    root = packages.get("", {})
    for name in _npm_direct_names(root):
        entry = packages.get("node_modules/" + name)
        if entry and (entry.get("link") or str(entry.get("version", "")).startswith(("file:", "link:"))):
            skipped.append(Skipped(name, rel, "local package"))
            continue
        if not entry or not entry.get("version"):
            skipped.append(Skipped(name, rel, "not resolved in lockfile"))
            continue
        deps.append(Dep("npm", name, entry["version"], rel))
    return deps, skipped


_RANGE_FLOOR = re.compile(r"^\s*(?:\^|~|>=|=|v)?\s*(\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?)\s*$")


def parse_package_json(path: str, rel: str) -> tuple:
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    deps: List[Dep] = []
    skipped: List[Skipped] = []
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in (manifest.get(key) or {}).items():
            m = _RANGE_FLOOR.match(str(spec))
            if not m:
                skipped.append(Skipped(name, rel, "range %r has no single floor version" % spec))
                continue
            version = m.group(1)
            # "1.3.0" pins exactly; "19", "1.2", "^1.2.3", "~1.2.3", ">=1.2.3" are ranges
            exact = str(spec).strip().lstrip("v=").strip() == version and version.count(".") >= 2
            while version.count(".") < 2 and "-" not in version:
                version += ".0"
            deps.append(Dep("npm", name, version, rel, exact=exact))
    return deps, skipped


def discover(root: str) -> tuple:
    """Return (deps, skipped, files_read) for a project directory."""
    deps: List[Dep] = []
    skipped: List[Skipped] = []
    files: List[str] = []

    def take(result: tuple, rel: str) -> None:
        deps.extend(result[0])
        skipped.extend(result[1])
        files.append(rel)

    entries = sorted(os.listdir(root))
    for fname in entries:
        if re.match(r"^requirements.*\.txt$", fname):
            take(parse_requirements(os.path.join(root, fname), fname), fname)
    if "uv.lock" in entries:
        take(parse_uv_lock(os.path.join(root, "uv.lock"), "uv.lock"), "uv.lock")
    if "package-lock.json" in entries:
        take(parse_package_lock(os.path.join(root, "package-lock.json"), "package-lock.json"), "package-lock.json")
    elif "package.json" in entries:
        take(parse_package_json(os.path.join(root, "package.json"), "package.json"), "package.json")

    # one row per (ecosystem, name, version); keep the first source seen
    unique: List[Dep] = []
    seen = set()
    for d in deps:
        key = (d.ecosystem, d.name, d.version)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique, skipped, files
