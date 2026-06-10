"""Brain Wiki ingest — fold one already-scraped video into the compounding wiki.

Reads from the Raw Lake (immutable), quotes the DB-computed outlier multiplier, asks the
LLM for a structured source summary + style card, and writes/updates the source, channel,
format, and audience pages plus the index and log. Never edits the Raw Lake; never invents
a number. See ``backend/brain_wiki/CLAUDE.md`` for the schema this implements.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, select

from .. import brain
from ..generation import prompts
from ..llm.base import LLMProvider
from ..llm.factory import require_llm
from ..llm.parse import complete_json
from ..models import Comment, Transcript, Video
from . import render
from .store import WikiStore

log = logging.getLogger("brain.wiki")

MAX_TRANSCRIPT_CHARS = 6000
MAX_COMMENTS = 30
MAX_SIGNALS = 3


@dataclass
class IngestResult:
    video_id: str
    multiplier: float | None
    pages_touched: list[str] = field(default_factory=list)


def _multiplier(session: Session, video: Video) -> float | None:
    """Outlier multiplier = views ÷ channel median, straight from the Raw Lake."""
    medians = {b.channel_id: b.median_views for b in brain.channel_baselines(session)}
    med = medians.get(video.channel_id, 0.0)
    return round(video.views / med, 2) if med > 0 else None


def ingest_video(
    session: Session,
    store: WikiStore,
    video_id: str,
    *,
    today: date,
    llm: LLMProvider | None = None,
) -> IngestResult:
    llm = llm or require_llm()
    video = session.get(Video, video_id)
    if video is None:
        raise ValueError(f"video {video_id!r} is not in the Raw Lake")

    tr = session.get(Transcript, video_id)
    transcript_excerpt = (tr.text if tr else "")[:MAX_TRANSCRIPT_CHARS]
    comments = session.exec(
        select(Comment).where(Comment.video_id == video_id).order_by(Comment.likes.desc()).limit(MAX_COMMENTS)
    ).all()
    comment_lines = (
        "\n".join(f"({c.likes}👍) {c.text.strip()[:200]}" for c in comments if c.text.strip()) or "(none)"
    )
    mult = _multiplier(session, video)

    # 1) Structured source summary (LLM).
    system, prompt = prompts.source_summary(
        video.title, video.channel_name or video.channel_id, transcript_excerpt, comment_lines
    )
    summary = complete_json(llm, prompt, system=system) or {}
    if not isinstance(summary, dict):
        summary = {}

    touched: list[str] = []
    # 2) Source page (atomic unit).
    touched.append(render.source_page(store, video, summary, mult, today))
    # 3) Channel entity page (style card + outlier history).
    touched.append(render.channel_page(session, store, video, mult, llm, today))
    # 4) Format concept page (deterministic merge — no extra LLM call).
    fmt = str(summary.get("format", "")).strip()
    if fmt:
        touched.append(render.format_page(store, fmt, summary, video, mult, today))
    # 5) Audience pages (bounded).
    for sig in (summary.get("audience_signals") or [])[:MAX_SIGNALS]:
        rel = render.audience_page(store, sig, video, today)
        if rel:
            touched.append(rel)
    # 6) Index + log.
    render.rebuild_index(store, today)
    channel = video.channel_name or video.channel_id
    mult_s = f"{mult}×" if mult is not None else "—"
    store.append_log(
        f"## [{today.isoformat()}] ingest | {channel} — {video.title} ({mult_s})\n"
        f"touched: {', '.join(touched)}"
    )
    return IngestResult(video_id=video_id, multiplier=mult, pages_touched=touched)


def already_ingested(store: WikiStore) -> set[str]:
    """Video ids that already have a source page."""
    ids: set[str] = set()
    for rel in store.list("sources"):
        page = store.read(rel)
        if page and page[0].get("video_id"):
            ids.add(str(page[0]["video_id"]))
    return ids


def backfill(
    session: Session,
    store: WikiStore,
    *,
    today: date,
    limit: int = 10,
    llm: LLMProvider | None = None,
) -> list[IngestResult]:
    """Fold the most-recent not-yet-ingested Raw-Lake videos into the wiki, capped at ``limit``.

    Lets an existing Brain (videos already scraped) populate the wiki without re-scraping. One
    bad video never stops the run.
    """
    llm = llm or require_llm()
    done = already_ingested(store)
    todo = [
        vid
        for vid in session.exec(select(Video.id).order_by(Video.ingested_at.desc())).all()
        if vid not in done
    ][: max(0, limit)]

    results: list[IngestResult] = []
    for vid in todo:
        try:
            results.append(ingest_video(session, store, vid, today=today, llm=llm))
        except Exception as exc:  # pragma: no cover - best-effort
            log.warning("backfill skipped %s: %s", vid, exc)
    return results
