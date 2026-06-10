"""Read side of the Brain Wiki — turn pages into generation context.

Mirrors the DB insight reads in ``generation/ideas.py`` so the script writer can be fed from
the compounding wiki instead of the recomputed DB tables. Quantitative signals — trending,
outliers, transcript search, and the virality gate — still come from the DB / model; this
module only supplies the *qualitative* layer (creator style, proven formats, audience pains).

All numbers returned here originate from page frontmatter that was itself populated from the
Raw Lake at ingest time, so they remain traceable.
"""
from __future__ import annotations

from typing import Any

from .render import slugify
from .store import WikiStore


def _pages(store: WikiStore, subdir: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in store.list(subdir):
        page = store.read(rel)
        if page:
            out.append(page[0])
    return out


def channel_style(
    store: WikiStore, *, channel_id: str | None = None, channel_name: str | None = None
) -> dict[str, Any] | None:
    """The stored style card for a channel, looked up by name slug then by ``channel_id``."""
    if channel_name:
        page = store.read(f"channels/{slugify(channel_name)}.md")
        if page and page[0].get("style"):
            return page[0]["style"]
    if channel_id:
        for fm in _pages(store, "channels"):
            if fm.get("channel_id") == channel_id and fm.get("style"):
                return fm["style"]
    return None


def formats(store: WikiStore, *, limit: int = 6) -> list[dict[str, Any]]:
    """Proven formats, strongest average outlier first."""
    rows = [
        {
            "label": fm.get("title", ""),
            "avg_multiplier": fm.get("avg_multiplier"),
            "summary": fm.get("summary", ""),
            "source_count": fm.get("source_count", 0),
        }
        for fm in _pages(store, "formats")
        if fm.get("title")
    ]
    rows.sort(key=lambda r: (r["avg_multiplier"] or 0), reverse=True)
    return rows[:limit]


def pains(store: WikiStore, *, limit: int = 8) -> list[dict[str, Any]]:
    """Audience pain-points, most-evidenced first."""
    rows = [
        {"question": fm.get("title", ""), "source_count": fm.get("source_count", 0)}
        for fm in _pages(store, "audience")
        if fm.get("title")
    ]
    rows.sort(key=lambda r: r["source_count"], reverse=True)
    return rows[:limit]


def overview(store: WikiStore) -> str:
    """The synthesis page body, if one has been written."""
    page = store.read("overview.md")
    return (page[1].strip() if page else "")


def counts(store: WikiStore) -> dict[str, int]:
    """Page counts per category — a cheap health/status view (no LLM)."""
    return {sub: len(store.list(sub)) for sub in ("sources", "channels", "formats", "audience", "queries")}
