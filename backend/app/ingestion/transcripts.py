"""Stub — LinkedIn posts are text-based; no transcript pipeline needed."""
from __future__ import annotations

from sqlmodel import Session


def backfill_missing(session: Session, *, channel_id: str | None = None, limit: int = 300, on_progress=None) -> dict:
    return {"total": 0, "fetched": 0, "unavailable": 0, "blocked": 0}
