"""Brain Wiki — the LLM-maintained qualitative knowledge layer (karpathy's LLM-Wiki pattern).

A compounding, interlinked markdown wiki that sits beside the quantitative core. The DB +
virality model stay authoritative on numbers; the wiki explains *why* and accumulates over
time instead of being recomputed. Opt-in via ``BRAIN_WIKI_ENABLED``. See
``backend/brain_wiki/CLAUDE.md`` for the schema.
"""
from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from .ingest import IngestResult, backfill, ingest_video
from .store import WikiStore

__all__ = ["WikiStore", "ingest_video", "backfill", "IngestResult", "default_store"]


def default_store() -> WikiStore:
    """The wiki store at the configured ``BRAIN_WIKI_DIR`` (relative to the backend/)."""
    root = Path(get_settings().brain_wiki_dir)
    if not root.is_absolute():
        # backend/app/wiki/__init__.py -> backend/
        root = Path(__file__).resolve().parents[2] / root
    return WikiStore(root)
