"""Semantic search stub — LinkedIn edition.

Post text search is handled directly in the brain API via SQL LIKE.
This module is kept as a stub so imports from agent.py don't break.
"""
from __future__ import annotations

from sqlmodel import Session


def search(session: Session, query: str, *, k: int = 8) -> list[dict]:
    """Keyword search over post text (stub — full implementation in brain API)."""
    return []


def index_video(session: Session, video_id: str, text: str) -> int:
    """No-op for LinkedIn (posts are indexed inline in brain.content_gaps)."""
    return 0
