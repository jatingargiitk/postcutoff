"""Command line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .agentsmd import render_markdown, write_block
from .analyze import LEVELS, Report, analyze, parse_cutoff
from .registry import Registry, RegistryError
from .sources import discover

LABELS = {
    "new-package": "NEW PACKAGE",
    "major": "MAJOR",
    "minor": "MINOR",
    "patch": "patch",
    "unknown": "unknown",
    "ok": "ok",
}


def render_text(report: Report, show_ok: bool) -> str:
    rows = [f for f in report.findings if show_ok or f.level != "ok"]
    lines = ["knowledge cutoff: %s   files: %s" % (report.cutoff.isoformat(), ", ".join(report.files) or "-")]
    if rows:
        head = ("LEVEL", "PACKAGE", "PINNED", "RELEASED", "NEWEST BEFORE CUTOFF")
        table = [head]
        for f in rows:
            pinned = f.dep.version + ("" if f.dep.exact else " (range floor)")
            if f.level == "new-package":
                known = "- (%s)" % f.note
            elif f.level == "unknown":
                known = "- (%s)" % f.note
            else:
                known = "%s (%s)" % (f.known, f.known_date.isoformat()) if f.known else "-"
            name = f.dep.name if f.dep.ecosystem == "pypi" else "npm:" + f.dep.name
            table.append((LABELS[f.level], name, pinned,
                          f.released.isoformat() if f.released else "-", known))
        widths = [max(len(r[i]) for r in table) for i in range(4)]
        for r in table:
            lines.append("  ".join(r[i].ljust(widths[i]) for i in range(4)) + "  " + r[4])
    c = report.counts()
    lines.append("")
    lines.append(
        "%d deps: %d new package, %d major, %d minor, %d patch, %d ok, %d unknown"
        % (len(report.findings), c["new-package"], c["major"], c["minor"], c["patch"], c["ok"], c["unknown"])
    )
    hidden = c["ok"] if not show_ok else 0
    if hidden:
        lines.append("(%d ok %s hidden; --all shows %s)" % (
            hidden, "row" if hidden == 1 else "rows", "it" if hidden == 1 else "them"))
    if report.skipped:
        lines.append("skipped %d: %s" % (
            len(report.skipped),
            ", ".join("%s (%s: %s)" % (s.name, s.source, s.reason) for s in report.skipped)))
    return "\n".join(lines)


def render_json(report: Report) -> str:
    out = {
        "cutoff": report.cutoff.isoformat(),
        "files": report.files,
        "counts": report.counts(),
        "findings": [
            {
                "ecosystem": f.dep.ecosystem,
                "name": f.dep.name,
                "version": f.dep.version,
                "exact": f.dep.exact,
                "source": f.dep.source,
                "level": f.level,
                "released": f.released.isoformat() if f.released else None,
                "newest_before_cutoff": f.known,
                "newest_before_cutoff_released": f.known_date.isoformat() if f.known_date else None,
                "first_release": f.first_release.isoformat() if f.first_release else None,
                "releases_after_cutoff_up_to_pin": f.newer_after_cutoff,
                "note": f.note,
            }
            for f in report.findings
        ],
        "skipped": [{"name": s.name, "source": s.source, "reason": s.reason} for s in report.skipped],
    }
    return json.dumps(out, indent=2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="postcutoff",
        description="List the dependencies pinned in a project that were released after "
                    "a model's knowledge cutoff, so you know where your coding agent is "
                    "writing from stale memory.",
    )
    p.add_argument("path", nargs="?", default=".", help="project directory (default: .)")
    p.add_argument("--cutoff", required=True, metavar="DATE",
                   help="the model's knowledge cutoff: YYYY-MM (end of month) or YYYY-MM-DD")
    p.add_argument("--format", choices=["text", "json", "md"], default="text",
                   help="md prints the block --write would insert")
    p.add_argument("--all", action="store_true", help="also list deps the model could have seen")
    p.add_argument("--fail-on", choices=LEVELS[1:], metavar="LEVEL",
                   help="exit 1 if any dep is at this level or worse "
                        "(patch < minor < major < new-package)")
    p.add_argument("--write", metavar="FILE",
                   help="insert or refresh a 'newer than your training data' block in FILE "
                        "(e.g. AGENTS.md or CLAUDE.md), between postcutoff markers")
    p.add_argument("--registry-file", metavar="JSON",
                   help="read release dates from this file instead of PyPI/npm "
                        '({"pypi": {"name": {"version": "YYYY-MM-DD"}}, "npm": {...}})')
    p.add_argument("--no-cache", action="store_true", help="don't read or write ~/.cache/postcutoff")
    p.add_argument("--version", action="version", version="postcutoff " + __version__)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cutoff = parse_cutoff(args.cutoff)
    except ValueError as exc:
        print("postcutoff: %s" % exc, file=sys.stderr)
        return 2
    if not os.path.isdir(args.path):
        print("postcutoff: %s is not a directory" % args.path, file=sys.stderr)
        return 2
    deps, skipped, files = discover(args.path)
    if not files:
        print("postcutoff: no requirements*.txt, uv.lock, package-lock.json or package.json in %s"
              % args.path, file=sys.stderr)
        return 2
    registry = Registry(fixture=args.registry_file, use_cache=not args.no_cache)
    try:
        report = analyze(deps, registry, cutoff)
    except RegistryError as exc:
        print("postcutoff: registry lookup failed: %s" % exc, file=sys.stderr)
        return 2
    report.skipped = skipped
    report.files = files
    if args.format == "json":
        print(render_json(report))
    elif args.format == "md":
        print(render_markdown(report), end="")
    else:
        print(render_text(report, args.all))
    if args.write:
        target = args.write if os.path.isabs(args.write) else os.path.join(args.path, args.write)
        status = write_block(target, render_markdown(report))
        print("%s: %s" % (target, status), file=sys.stderr)
    if args.fail_on and report.at_least(args.fail_on):
        return 1
    return 0
