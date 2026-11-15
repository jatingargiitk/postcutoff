import datetime as dt

import pytest

from conftest import REGISTRY
from postcutoff.analyze import analyze, classify, parse_cutoff
from postcutoff.registry import Registry, timeline_from_npm, timeline_from_pypi
from postcutoff.sources import Dep

D = dt.date


def test_parse_cutoff():
    assert parse_cutoff("2025-01") == D(2025, 1, 31)
    assert parse_cutoff("2024-02") == D(2024, 2, 29)
    assert parse_cutoff("2025-03-15") == D(2025, 3, 15)
    for bad in ("2025", "2025-13", "jan 2025"):
        with pytest.raises(ValueError):
            parse_cutoff(bad)


def tl(**kw):
    return {k.replace("_", "."): D.fromisoformat(v) for k, v in kw.items()}


def test_minor_gap_ignores_prerelease_before_cutoff():
    t = {"2.10.6": D(2025, 1, 24), "2.11.0b1": D(2025, 1, 30), "2.11.3": D(2025, 4, 8),
         "2.11.0": D(2025, 3, 27)}
    f = classify(Dep("pypi", "pydantic", "2.11.3", "r"), t, D(2025, 1, 31))
    assert (f.level, f.known, f.released) == ("minor", "2.10.6", D(2025, 4, 8))
    assert f.newer_after_cutoff == 2  # 2.11.0 and 2.11.3


def test_ok_when_released_on_cutoff_day():
    f = classify(Dep("pypi", "x", "1.0.0", "r"), {"1.0.0": D(2025, 1, 31)}, D(2025, 1, 31))
    assert f.level == "ok"


def test_new_package():
    f = classify(Dep("npm", "brand-new", "1.0.0", "p"), {"1.0.0": D(2025, 3, 1)}, D(2025, 1, 31))
    assert f.level == "new-package" and f.known is None and "2025-03-01" in f.note


def test_unknown_cases():
    assert classify(Dep("npm", "a", "1.0.0", "p"), None, D(2025, 1, 1)).level == "unknown"
    assert classify(Dep("npm", "a", "1.0.0", "p"), {}, D(2025, 1, 1)).level == "unknown"
    f = classify(Dep("npm", "a", "9.9.9", "p"), {"1.0.0": D(2020, 1, 1)}, D(2025, 1, 1))
    assert f.level == "unknown" and "not published" in f.note


def test_version_spelling_is_normalised():
    f = classify(Dep("npm", "react", "19.0.0", "p"), {"19.0": D(2024, 12, 5)}, D(2025, 1, 31))
    assert f.level == "ok"


def test_only_prereleases_before_cutoff():
    t = {"1.0.0rc1": D(2024, 12, 1), "1.0.0": D(2025, 2, 1)}
    f = classify(Dep("pypi", "x", "1.0.0", "r"), t, D(2025, 1, 31))
    assert f.known == "1.0.0rc1" and f.level == "patch"


def test_analyze_sorts_worst_first():
    deps = [Dep("pypi", "httpx", "0.28.1", "r"), Dep("npm", "brand-new", "1.0.0", "p"),
            Dep("npm", "zod", "4.0.5", "p"), Dep("pypi", "pydantic", "2.11.3", "r")]
    report = analyze(deps, Registry(fixture=REGISTRY), D(2025, 1, 31))
    assert [f.level for f in report.findings] == ["new-package", "major", "minor", "ok"]
    assert [f.dep.name for f in report.at_least("major")] == ["brand-new", "zod"]
    assert report.counts()["minor"] == 1


def test_timeline_parsers():
    pypi = {"releases": {"1.0": [{"upload_time_iso_8601": "2024-05-02T10:00:00.1Z"},
                                 {"upload_time_iso_8601": "2024-05-01T23:00:00Z"}],
                         "1.1": []}}
    assert timeline_from_pypi(pypi) == {"1.0": D(2024, 5, 1)}
    npm = {"versions": {"1.0.0": {}}, "time": {"created": "2020-01-01T00:00:00Z",
                                                "modified": "2025-01-01T00:00:00Z",
                                                "1.0.0": "2024-01-02T00:00:00.000Z",
                                                "0.9.0": "2023-01-01T00:00:00.000Z"}}
    assert timeline_from_npm(npm) == {"1.0.0": D(2024, 1, 2)}  # 0.9.0 was unpublished


def test_registry_cache_roundtrip(tmp_path, monkeypatch):
    r = Registry(cache_dir=str(tmp_path))
    calls = []

    def fake_get(url):
        calls.append(url)
        return {"versions": {"1.0.0": {}}, "time": {"1.0.0": "2024-01-02T00:00:00Z"}}

    monkeypatch.setattr(r, "_get_json", fake_get)
    assert r.timeline("npm", "@scope/pkg") == {"1.0.0": D(2024, 1, 2)}
    assert r.timeline("npm", "@scope/pkg") == {"1.0.0": D(2024, 1, 2)}
    assert calls == ["https://registry.npmjs.org/@scope%2Fpkg"]


def test_registry_404_is_cached_as_missing(tmp_path, monkeypatch):
    r = Registry(cache_dir=str(tmp_path))
    monkeypatch.setattr(r, "_get_json", lambda url: None)
    assert r.timeline("pypi", "nope") is None
    monkeypatch.setattr(r, "_get_json", lambda url: 1 / 0)
    assert r.timeline("pypi", "nope") is None
