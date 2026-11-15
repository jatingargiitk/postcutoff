import datetime as dt
import os

from conftest import DATA, REGISTRY
from postcutoff.agentsmd import END, START, link, render_markdown, write_block
from postcutoff.analyze import Report, analyze
from postcutoff.cli import main
from postcutoff.registry import Registry
from postcutoff.sources import Dep


def report(*deps):
    return analyze(list(deps), Registry(fixture=REGISTRY), dt.date(2025, 1, 31))


def test_block_lists_unseen_versions_only():
    md = render_markdown(report(Dep("npm", "zod", "4.0.5", "p"), Dep("pypi", "httpx", "0.28.1", "r"),
                                Dep("npm", "brand-new", "1.0.0", "p")))
    assert md.startswith(START) and md.rstrip().endswith(END)
    assert "released after 2025-01-31" in md
    assert ("- `zod` (npm) 4.0.5 (new major version, released 2025-07-10); the newest version you "
            "may know is 3.24.1: https://www.npmjs.com/package/zod/v/4.0.5") in md
    assert "- `brand-new` (npm) 1.0.0 (the package did not exist yet, released 2025-03-01): " in md
    assert "httpx" not in md


def test_block_when_everything_is_known():
    md = render_markdown(report(Dep("pypi", "httpx", "0.28.1", "r")))
    assert "Every pinned dependency in this project was released on or before 2025-01-31" in md


def test_links():
    assert link("pypi", "pydantic", "2.11.3") == "https://pypi.org/project/pydantic/2.11.3/"
    assert link("npm", "@anthropic-ai/sdk", "0.57.0") == "https://www.npmjs.com/package/@anthropic-ai/sdk/v/0.57.0"


def test_write_block_create_append_replace(tmp_path):
    p = str(tmp_path / "AGENTS.md")
    assert write_block(p, START + "\nv1\n" + END + "\n") == "created"
    assert write_block(p, START + "\nv1\n" + END + "\n") == "unchanged"
    with open(p, "w") as fh:
        fh.write("# Rules\nUse uv.")
    assert write_block(p, START + "\nv1\n" + END + "\n") == "updated"
    with open(p, "a") as fh:
        fh.write("\n## After\nkeep me\n")
    assert write_block(p, START + "\nv2\n" + END + "\n") == "updated"
    text = open(p).read()
    assert text == "# Rules\nUse uv.\n\n" + START + "\nv2\n" + END + "\n\n## After\nkeep me\n"


def test_cli_write(tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("pydantic==2.11.3\n")
    (proj / "CLAUDE.md").write_text("# Project notes\n")
    code = main([str(proj), "--cutoff", "2025-01", "--registry-file", REGISTRY, "--write", "CLAUDE.md"])
    err = capsys.readouterr().err
    assert code == 0 and "CLAUDE.md: updated" in err
    text = (proj / "CLAUDE.md").read_text()
    assert text.startswith("# Project notes\n\n" + START)
    assert "`pydantic` 2.11.3 (new minor version" in text


def test_cli_md_format(capsys):
    assert main([os.path.join(DATA, "node"), "--cutoff", "2025-01", "--registry-file", REGISTRY,
                 "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n- ") == 3  # @anthropic-ai/sdk, vitest, zod
