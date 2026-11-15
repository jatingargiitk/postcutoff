import json
import os

from conftest import DATA, REGISTRY
from postcutoff.cli import main


def run(capsys, *args):
    code = main(list(args) + ["--registry-file", REGISTRY])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_text_report(capsys):
    code, out, _ = run(capsys, os.path.join(DATA, "py"), "--cutoff", "2025-01")
    assert code == 0
    assert "knowledge cutoff: 2025-01-31   files: requirements.txt, uv.lock" in out
    assert "MAJOR  fastmcp" in out
    assert "MINOR  pydantic" in out
    assert "patch  uvicorn" not in out  # uvicorn 0.34.0 predates the cutoff
    assert "(3 ok rows hidden; --all shows them)" in out
    assert "skipped 1: fastapi (requirements.txt: not pinned with ==)" in out


def test_all_shows_ok_rows(capsys):
    _, out, _ = run(capsys, os.path.join(DATA, "py"), "--cutoff", "2025-01", "--all")
    assert "ok     httpx" in out and "hidden" not in out


def test_fail_on(capsys):
    path = os.path.join(DATA, "py")
    assert run(capsys, path, "--cutoff", "2025-01", "--fail-on", "major")[0] == 1
    # by the end of May 2025 only pytest 8.4.1 (June 18) is still unseen: a minor gap
    assert run(capsys, path, "--cutoff", "2025-05", "--fail-on", "major")[0] == 0
    assert run(capsys, path, "--cutoff", "2025-05", "--fail-on", "minor")[0] == 1
    assert run(capsys, path, "--cutoff", "2025-06", "--fail-on", "patch")[0] == 0


def test_json_report(capsys):
    code, out, _ = run(capsys, os.path.join(DATA, "nodenolock"), "--cutoff", "2025-01", "--format", "json")
    doc = json.loads(out)
    assert code == 0 and doc["cutoff"] == "2025-01-31"
    by = {f["name"]: f for f in doc["findings"]}
    assert by["zod"]["level"] == "major" and by["zod"]["exact"] is False
    assert by["zod"]["newest_before_cutoff"] == "3.24.1"
    assert by["left-pad"]["level"] == "unknown"
    assert by["react"]["level"] == "ok"
    assert doc["skipped"][0]["name"] == "weird"


def test_usage_errors(capsys, tmp_path):
    assert run(capsys, str(tmp_path), "--cutoff", "2025-01")[0] == 2
    code, _, err = run(capsys, str(tmp_path), "--cutoff", "soon")
    assert code == 2 and "YYYY-MM" in err
    assert run(capsys, str(tmp_path / "missing"), "--cutoff", "2025-01")[0] == 2
