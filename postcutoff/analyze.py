"""Compare each pinned dependency with what existed at a knowledge cutoff."""
from __future__ import annotations

import calendar
import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .registry import Registry, Timeline
from .sources import Dep
from .versions import gap, is_prerelease, same_release, sort_key

# ordered from least to most surprising for the model
LEVELS = ["ok", "patch", "minor", "major", "new-package"]


def parse_cutoff(text: str) -> _dt.date:
    """YYYY-MM-DD, or YYYY-MM meaning the last day of that month."""
    text = text.strip()
    m = re.match(r"^(\d{4})-(\d{2})$", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            raise ValueError("bad month in cutoff %r" % text)
        return _dt.date(year, month, calendar.monthrange(year, month)[1])
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError("cutoff must be YYYY-MM or YYYY-MM-DD, got %r" % text) from None


@dataclass
class Finding:
    dep: Dep
    level: str  # one of LEVELS, or "unknown"
    released: Optional[_dt.date] = None
    known: Optional[str] = None  # newest final release on or before the cutoff
    known_date: Optional[_dt.date] = None
    first_release: Optional[_dt.date] = None
    note: str = ""
    newer_after_cutoff: int = 0  # releases between `known` and the pin


def _find_version(tl: Timeline, version: str) -> Optional[str]:
    if version in tl:
        return version
    for v in tl:
        if same_release(v, version):
            return v
    return None


def classify(dep: Dep, tl: Optional[Timeline], cutoff: _dt.date) -> Finding:
    if tl is None:
        return Finding(dep, "unknown", note="not found on %s" % dep.ecosystem)
    if not tl:
        return Finding(dep, "unknown", note="no dated releases on %s" % dep.ecosystem)
    first = min(tl.values())
    match = _find_version(tl, dep.version)
    if match is None:
        return Finding(dep, "unknown", first_release=first,
                       note="version %s not published on %s" % (dep.version, dep.ecosystem))
    released = tl[match]
    before = [v for v, d in tl.items() if d <= cutoff and not is_prerelease(v)]
    if not before:
        before = [v for v, d in tl.items() if d <= cutoff]
    known = max(before, key=sort_key) if before else None
    f = Finding(dep, "ok", released=released, known=known,
                known_date=tl[known] if known else None, first_release=first)
    if first > cutoff:
        f.level = "new-package"
        f.note = "first published %s" % first.isoformat()
        return f
    if released <= cutoff:
        return f
    f.newer_after_cutoff = sum(
        1 for v, d in tl.items()
        if d > cutoff and not is_prerelease(v) and sort_key(v) <= sort_key(match)
    )
    f.level = gap(match, known) if known else "major"
    return f


@dataclass
class Report:
    cutoff: _dt.date
    findings: List[Finding] = field(default_factory=list)
    skipped: list = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    def at_least(self, level: str) -> List[Finding]:
        floor = LEVELS.index(level)
        return [f for f in self.findings if f.level in LEVELS and LEVELS.index(f.level) >= floor]

    def counts(self) -> dict:
        out = {k: 0 for k in LEVELS + ["unknown"]}
        for f in self.findings:
            out[f.level] += 1
        return out


def analyze(deps: List[Dep], registry: Registry, cutoff: _dt.date) -> Report:
    report = Report(cutoff)
    for dep in deps:
        report.findings.append(classify(dep, registry.timeline(dep.ecosystem, dep.name), cutoff))
    order = {lvl: i for i, lvl in enumerate(["new-package", "major", "minor", "patch", "unknown", "ok"])}
    report.findings.sort(key=lambda f: (order[f.level], f.dep.ecosystem, f.dep.name))
    return report
