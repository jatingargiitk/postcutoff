"""Release timelines from PyPI and npm, with an on-disk cache.

A timeline maps every published version to the date (UTC) it first appeared.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

from . import __version__

Timeline = Dict[str, _dt.date]

USER_AGENT = "postcutoff/%s (+https://github.com/jatingargiitk/postcutoff)" % __version__
CACHE_TTL = 24 * 3600


class RegistryError(Exception):
    pass


def _date(value: str) -> _dt.date:
    return _dt.date.fromisoformat(value[:10])


def pypi_url(name: str) -> str:
    return "https://pypi.org/pypi/%s/json" % urllib.parse.quote(name)


def npm_url(name: str) -> str:
    # scoped packages keep their @ but the slash is encoded
    return "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@")


def timeline_from_pypi(doc: dict) -> Timeline:
    out: Timeline = {}
    for version, files in (doc.get("releases") or {}).items():
        stamps = [f.get("upload_time_iso_8601") or f.get("upload_time") for f in files]
        stamps = [s for s in stamps if s]
        if stamps:
            out[version] = min(_date(s) for s in stamps)
    return out


def timeline_from_npm(doc: dict) -> Timeline:
    out: Timeline = {}
    published = set((doc.get("versions") or {}).keys())
    for version, stamp in (doc.get("time") or {}).items():
        if version in ("created", "modified"):
            continue
        # unpublished versions stay in `time` but leave `versions`
        if published and version not in published:
            continue
        out[version] = _date(stamp)
    return out


class Registry:
    """Fetch timelines live, or from a fixture file for offline use."""

    def __init__(self, cache_dir: Optional[str] = None, fixture: Optional[str] = None,
                 timeout: float = 20.0, use_cache: bool = True):
        self.timeout = timeout
        self.fixture: Optional[dict] = None
        if fixture:
            with open(fixture, encoding="utf-8") as fh:
                self.fixture = json.load(fh)
        if cache_dir is None:
            base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
            cache_dir = os.path.join(base, "postcutoff")
        self.cache_dir = cache_dir
        self.use_cache = use_cache and self.fixture is None
        self.fetches = 0

    def timeline(self, ecosystem: str, name: str) -> Optional[Timeline]:
        """Return the timeline, or None if the registry has no such package."""
        if self.fixture is not None:
            entry = (self.fixture.get(ecosystem) or {}).get(name)
            if entry is None:
                return None
            return {v: _date(d) for v, d in entry.items()}
        cached = self._cache_get(ecosystem, name)
        if cached is not None:
            return cached or None
        url = pypi_url(name) if ecosystem == "pypi" else npm_url(name)
        doc = self._get_json(url)
        if doc is None:
            self._cache_put(ecosystem, name, {})
            return None
        tl = timeline_from_pypi(doc) if ecosystem == "pypi" else timeline_from_npm(doc)
        self._cache_put(ecosystem, name, tl)
        return tl

    def _get_json(self, url: str) -> Optional[dict]:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.fetches += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RegistryError("%s: HTTP %s" % (url, exc.code)) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RegistryError("%s: %s" % (url, exc)) from exc

    def _cache_path(self, ecosystem: str, name: str) -> str:
        safe = urllib.parse.quote(name, safe="")
        return os.path.join(self.cache_dir, ecosystem, safe + ".json")

    def _cache_get(self, ecosystem: str, name: str) -> Optional[Timeline]:
        if not self.use_cache:
            return None
        path = self._cache_path(ecosystem, name)
        try:
            if time.time() - os.path.getmtime(path) > CACHE_TTL:
                return None
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return None
        return {v: _date(d) for v, d in raw.items()}

    def _cache_put(self, ecosystem: str, name: str, tl: Timeline) -> None:
        if not self.use_cache:
            return
        path = self._cache_path(ecosystem, name)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({v: d.isoformat() for v, d in tl.items()}, fh)
            os.replace(tmp, path)
        except OSError:
            pass
