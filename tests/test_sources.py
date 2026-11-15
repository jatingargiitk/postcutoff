import json
import os

from conftest import DATA
from postcutoff.sources import discover, parse_package_json, parse_requirements, parse_uv_lock


def test_requirements_pins_and_skips():
    deps, skipped = parse_requirements(os.path.join(DATA, "py", "requirements.txt"), "requirements.txt")
    assert [(d.name, d.version) for d in deps] == [
        ("pydantic", "2.11.3"), ("requests", "2.32.3"), ("uvicorn", "0.34.0")]
    assert [s.name for s in skipped] == ["fastapi"]


def test_uv_lock_direct_deps_only():
    deps, skipped = parse_uv_lock(os.path.join(DATA, "py", "uv.lock"), "uv.lock")
    assert sorted((d.name, d.version) for d in deps) == [
        ("fastmcp", "2.3.4"), ("httpx", "0.28.1"), ("pytest", "8.4.1")]
    assert skipped == []  # anyio is transitive, so it is not reported


def test_uv_lock_missing_version_is_skipped(tmp_path):
    p = tmp_path / "uv.lock"
    p.write_text('[[package]]\nname = "app"\nversion = "1"\nsource = { editable = "." }\n'
                 'dependencies = [{ name = "ghost" }]\n')
    deps, skipped = parse_uv_lock(str(p), "uv.lock")
    assert deps == [] and [s.name for s in skipped] == ["ghost"]


def test_package_lock_direct_deps_skip_links():
    deps, skipped, files = discover(os.path.join(DATA, "node"))
    assert files == ["package-lock.json"]  # package.json is ignored when a lockfile exists
    assert sorted((d.name, d.version) for d in deps) == [
        ("@anthropic-ai/sdk", "0.57.0"), ("vitest", "3.2.4"), ("zod", "4.0.5")]
    assert [(s.name, s.reason) for s in skipped] == [("local", "local package")]


def test_package_lock_v1_is_reported(tmp_path):
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 1, "dependencies": {}}))
    deps, skipped, _ = discover(str(tmp_path))
    assert deps == [] and "lockfileVersion 1" in skipped[0].reason


def test_package_json_range_floors():
    deps, skipped = parse_package_json(os.path.join(DATA, "nodenolock", "package.json"), "package.json")
    got = {d.name: (d.version, d.exact) for d in deps}
    assert got == {"zod": ("4.0.5", False), "react": ("19.0.0", False), "left-pad": ("1.3.0", True)}
    assert [s.name for s in skipped] == ["weird"]


def test_discover_merges_and_dedupes(tmp_path):
    (tmp_path / "requirements.txt").write_text("httpx==0.28.1\n")
    (tmp_path / "requirements-dev.txt").write_text("httpx==0.28.1\npytest==8.4.1\n")
    deps, _, files = discover(str(tmp_path))
    assert files == ["requirements-dev.txt", "requirements.txt"]
    assert sorted(d.name for d in deps) == ["httpx", "pytest"]
