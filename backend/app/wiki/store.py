"""Filesystem store for the Brain Wiki — markdown pages with YAML frontmatter.

The wiki is just a directory of markdown files (a git repo of them, ideally). This module
is the only thing that touches that directory: it reads/writes pages, parses/serialises
frontmatter, and refuses any path that escapes the wiki root. Higher layers (`ingest`,
`render`) deal in relative page paths like ``sources/dQw4w9WgXcQ.md``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# A page path is a relative, lowercase, slash-separated .md file — nothing else.
_REL_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*\.md$")
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)

LOG_FILE = "log.md"
INDEX_FILE = "index.md"


class WikiStore:
    """Read/write markdown pages under a single wiki root, safely."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- path safety ----
    def _path(self, rel: str) -> Path:
        rel = rel.strip()
        if not _REL_RE.match(rel) or ".." in rel:
            raise ValueError(f"unsafe wiki page path: {rel!r}")
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            raise ValueError(f"page path escapes wiki root: {rel!r}")
        return p

    # ---- read / write ----
    def exists(self, rel: str) -> bool:
        return self._path(rel).exists()

    def read(self, rel: str) -> tuple[dict[str, Any], str] | None:
        """Return ``(frontmatter, body)`` or ``None`` if the page doesn't exist."""
        p = self._path(rel)
        if not p.exists():
            return None
        raw = p.read_text(encoding="utf-8")
        m = _FM_RE.match(raw)
        if not m:
            return {}, raw
        fm = yaml.safe_load(m.group(1)) or {}
        return (fm if isinstance(fm, dict) else {}), m.group(2)

    def write(self, rel: str, frontmatter: dict[str, Any], body: str) -> str:
        """Create/overwrite a page. Returns the relative path written."""
        p = self._path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        p.write_text(f"---\n{fm}\n---\n\n{body.strip()}\n", encoding="utf-8")
        return rel

    def list(self, subdir: str) -> list[str]:
        """Relative paths of every ``.md`` page under ``subdir`` (sorted)."""
        base = self._path(f"{subdir.strip('/')}/_.md").parent
        if not base.exists():
            return []
        return sorted(f"{subdir.strip('/')}/{f.name}" for f in base.glob("*.md"))

    # ---- log (append-only) ----
    def append_log(self, entry: str) -> None:
        p = self.root / LOG_FILE
        prefix = "" if not p.exists() else "\n"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(prefix + entry.rstrip() + "\n")
