"""Agentic content engine — the autonomous, self-learning creator loop (Layer G).

Turns the Brain into a weekly content producer: generate a batch of full content packages
(idea → title → script → description+CTA → thumbnail prompt) into a durable queue, learn from
the user's approve/decline feedback and from how published videos *actually* perform, and feed
that memory back into the next generation.

Reuses the existing pipeline end-to-end — `refine.craft` (research↔virality gate),
`script.generate_script/_description`, `ingest_source`, and `brain.*` — so this module is
orchestration + persistence, not new generation logic. The backtested virality model stays the
numeric gate; this layer adds the *qualitative*, compounding memory (Claude-driven "RL").
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime

from sqlmodel import Session, select

from . import brain, insights
from .config import get_settings
from .generation import prompts, refine
from .generation import script as script_gen
from .ingestion import scraper
from .ingestion.pipeline import ingest_source
from .llm.base import LLMProvider
from .llm.factory import require_llm
from .models import (
    ContentFeedback,
    ContentItem,
    ContentRun,
    ContentStatus,
    CreatorProfile,
    FeedbackKind,
    Source,
    Video,
)

log = logging.getLogger("brain.agent")

# An outlier multiplier at/above this counts as "it performed" (matches the system's
# standard proven-demand threshold used by the virality backtest).
VIRAL_THRESHOLD = 3.0

_noop: Callable[[str], None] = lambda _msg: None


# ---- Settings ----

def _set_phase(session: Session, run: ContentRun | None, phase: str) -> None:
    if run is not None:
        run.phase = phase
        session.add(run)
        session.commit()


def fail_interrupted_runs(session: Session) -> int:
    """Mark any ContentRun left 'running' (its worker thread died on a restart/crash) as error.

    Generation runs in a daemon thread; if the process stops mid-batch the run would otherwise
    hang at 'running' forever and the UI's progress bar would never resolve. Call on startup.
    """
    from .models import IngestStatus

    stale = session.exec(select(ContentRun).where(ContentRun.status == IngestStatus.running)).all()
    for run in stale:
        run.status = IngestStatus.error
        run.message = (run.message or "") + " (interrupted — backend restarted)"
        run.finished_at = datetime.utcnow()
        session.add(run)
    if stale:
        session.commit()
    return len(stale)


def get_profile(session: Session) -> CreatorProfile:
    """The single saved Settings row, created with defaults on first use."""
    profile = session.get(CreatorProfile, 1)
    if profile is None:
        profile = CreatorProfile(id=1)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


# ---- Learning memory (the Claude-driven "RL") ----

def _learning_context(session: Session) -> str:
    """Recent declines + published outcomes, as a text block fed into generation."""
    parts: list[str] = []

    declines = session.exec(
        select(ContentItem)
        .where(ContentItem.status == ContentStatus.declined)
        .order_by(ContentItem.updated_at.desc())
        .limit(8)
    ).all()
    if declines:
        parts.append(
            "RECENTLY DECLINED (do not repeat these or their flaws):\n"
            + "\n".join(f'- "{d.title}": {d.declined_reason}' for d in declines if d.declined_reason)
        )

    scored = session.exec(
        select(ContentItem)
        .where(ContentItem.status == ContentStatus.scored)
        .order_by(ContentItem.updated_at.desc())
        .limit(12)
    ).all()
    winners = [s for s in scored if s.performed]
    losers = [s for s in scored if s.performed is False]
    if winners:
        parts.append(
            "WHAT WORKED when published (replicate the pattern):\n"
            + "\n".join(f'- {s.actual_multiplier}x  "{s.title}"' for s in winners[:6])
        )
    if losers:
        parts.append(
            "WHAT UNDERPERFORMED (avoid the pattern):\n"
            + "\n".join(
                f'- {s.actual_multiplier}x (predicted {s.predicted_score})  "{s.title}"'
                for s in losers[:6]
            )
        )
    return "\n\n".join(parts)


def _agent_guidance(session: Session, profile: CreatorProfile, *, extra: str = "") -> str:
    base = "Propose a fresh, original YouTube video idea grounded in the channels' proven demand"
    if profile.niche:
        base += f" for the {profile.niche} niche"
    base += "."
    learned = _learning_context(session)
    return "\n\n".join(p for p in (base, learned, extra) if p)


# ---- Generation ----

def _thumbnail(llm: LLMProvider, title: str, angle: str, script_md: str) -> str:
    system, prompt = prompts.thumbnail_prompt(title, angle, script_md)
    return llm.complete(prompt, system=system).strip()


def _generate_one(
    session: Session,
    *,
    profile: CreatorProfile,
    llm: LLMProvider,
    batch_id: str,
    primary_channel: str | None,
    guidance: str,
    regenerated_from_id: int | None = None,
    on_progress: Callable[[str], None] = _noop,
) -> ContentItem:
    """Craft one full content package and persist it as a `proposed` item."""
    idea = refine.craft(
        session,
        llm=llm,
        channel_id=primary_channel,
        niche=profile.niche,
        guidance=guidance,
        target_score=profile.target_score,
        duration_sec=profile.duration_sec,
        on_progress=on_progress,
    )
    title = idea["title"]
    angle = idea.get("angle", "")
    on_progress(f'writing script — "{title[:40]}"')
    doc = script_gen.generate_script(
        session, title=title, angle=angle, channel_id=primary_channel, llm=llm,
        on_progress=on_progress,
    )
    on_progress("writing description + CTA")
    desc = script_gen.generate_description(
        session,
        title=title,
        angle=angle,
        script_markdown=doc["markdown"],
        niche=profile.niche,
        cta=(profile.offer or None),
        llm=llm,
    )
    on_progress("writing thumbnail prompt")
    thumb = _thumbnail(llm, title, angle, doc["markdown"])

    item = ContentItem(
        batch_id=batch_id,
        status=ContentStatus.proposed,
        title=title,
        angle=angle,
        format=idea.get("format", "other"),
        script_markdown=doc["markdown"],
        description=desc,
        thumbnail_prompt=thumb,
        evidence=[str(e) for e in (idea.get("evidence") or [])],
        sections=doc["sections"],
        predicted_score=idea.get("virality_score"),
        predicted_viral=idea.get("predicted_viral"),
        nearest_analogs=idea.get("nearest_analogs") or [],
        channel_id=primary_channel,
        niche=profile.niche,
        regenerated_from_id=regenerated_from_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def generate_batch(
    session: Session,
    *,
    llm: LLMProvider | None = None,
    n: int | None = None,
    batch_id: str | None = None,
    run: ContentRun | None = None,
    refresh: bool = True,
    topic: str | None = None,
    on_progress: Callable[[str], None] = _noop,
) -> list[ContentItem]:
    """Produce a batch of content packages into the queue.

    The weekly job calls this with refresh=True and no topic. "Generate on command" calls it
    with refresh=False (use existing Brain data, fast) and a specific topic.
    """
    llm = llm or require_llm()
    profile = get_profile(session)
    n = n or profile.n_per_week
    batch_id = batch_id or uuid.uuid4().hex[:12]

    if refresh:
        settings = get_settings()
        sources = session.exec(select(Source).where(Source.active == True)).all()  # noqa: E712
        _set_phase(session, run, "scraping")
        for i, src in enumerate(sources):

            def _cb(done: int, total: int, msg: str, _i: int = i) -> None:
                if run is not None:
                    run.scrape_done = done
                    run.scrape_total = total
                    run.message = f"channel {_i + 1}/{len(sources)}: {msg}"
                    session.add(run)
                    session.commit()
                on_progress(f"scraping {done}/{total}")

            try:
                ingest_source(
                    session, src,
                    max_new=settings.agent_max_videos_per_source,
                    popular_k=settings.agent_popular_per_source,
                    comment_limit=settings.comment_limit,
                    cap=True,
                    on_progress=_cb,
                )
            except Exception as exc:  # one source shouldn't stop the batch
                log.warning("agent refresh failed for source %s: %s", src.id, exc)

        _set_phase(session, run, "mining")
        on_progress("mining insights…")
        try:
            insights.mine_patterns(session, niche=profile.niche, min_multiplier=2.0, llm=llm)
            insights.mine_pain_points(session, niche=profile.niche, llm=llm)
        except Exception as exc:  # mining is best-effort (covers LLMError)
            log.info("agent mining skipped: %s", exc)

    primary = next(
        (s.external_id for s in session.exec(select(Source).where(Source.active == True)).all() if s.external_id),  # noqa: E712
        None,
    )
    extra = (
        f'Create a video specifically about: "{topic}". Treat this as the required subject.'
        if topic
        else ""
    )
    guidance = _agent_guidance(session, profile, extra=extra)

    _set_phase(session, run, "writing")
    items: list[ContentItem] = []
    for i in range(n):
        # Surface each sub-step (research / refine / script / description) to the run so the UI
        # shows live progress *within* an item, not just a frozen bar between items.
        def _wp(msg: str, _i: int = i) -> None:
            if run is not None:
                run.message = f"idea {_i + 1}/{n}: {msg}"
                session.add(run)
                session.commit()
            on_progress(msg)

        _wp("starting…")
        try:
            item = _generate_one(
                session, profile=profile, llm=llm, batch_id=batch_id,
                primary_channel=primary, guidance=guidance, on_progress=_wp,
            )
            items.append(item)
        except Exception as exc:
            log.warning("agent failed to craft item %s/%s: %s", i + 1, n, exc)
        if run is not None:
            run.n_done = len(items)
            session.add(run)
            session.commit()
    _set_phase(session, run, "done")
    return items


# ---- Review actions ----

def approve(session: Session, item_id: int) -> ContentItem:
    item = _require_item(session, item_id)
    item.status = ContentStatus.approved
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.add(ContentFeedback(item_id=item_id, kind=FeedbackKind.approve, reason=item.title))
    session.commit()
    session.refresh(item)
    return item


def schedule(session: Session, item_id: int, when: date) -> ContentItem:
    item = _require_item(session, item_id)
    item.scheduled_for = when
    item.status = ContentStatus.scheduled
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def mark_declined(session: Session, item_id: int, reason: str) -> ContentItem:
    """Quick, LLM-free part of a decline: flag it + log the feedback. Returns the declined item."""
    item = _require_item(session, item_id)
    item.status = ContentStatus.declined
    item.declined_reason = reason
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.add(
        ContentFeedback(item_id=item_id, kind=FeedbackKind.decline, reason=f'"{item.title}": {reason}')
    )
    session.commit()
    session.refresh(item)
    return item


def regenerate_from(session: Session, item_id: int, *, llm: LLMProvider | None = None) -> ContentItem:
    """Craft one replacement for an already-declined item, learning from its decline reason."""
    llm = llm or require_llm()
    item = _require_item(session, item_id)
    profile = get_profile(session)
    extra = (
        f'The previous idea "{item.title}" was DECLINED because: {item.declined_reason}. '
        "Produce a clearly different idea that fixes this — do not just reword it."
    )
    guidance = _agent_guidance(session, profile, extra=extra)
    return _generate_one(
        session, profile=profile, llm=llm, batch_id=item.batch_id,
        primary_channel=item.channel_id, guidance=guidance, regenerated_from_id=item_id,
    )


def decline(session: Session, item_id: int, reason: str, *, llm: LLMProvider | None = None) -> ContentItem:
    """Decline an item and craft a replacement that learns from the reason (returns the replacement)."""
    mark_declined(session, item_id, reason)
    return regenerate_from(session, item_id, llm=llm)


# ---- Publish + measure (the reward loop) ----

_VID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def _video_id_from_url(url: str) -> str | None:
    m = _VID_RE.search(url or "")
    return m.group(1) if m else None


def _measure(session: Session, item: ContentItem, *, fetcher=None) -> ContentItem:
    """(Re)measure a published item's real outlier multiplier and compute the reward."""
    vid = item.published_video_id
    if not vid:
        return item

    video = session.get(Video, vid)
    if video is None:  # not in the lake yet → scrape it once (metadata only, no comments)
        fetch = fetcher or (lambda v: scraper.fetch_video(v, with_comments=False, comment_limit=0))
        video = Video(**scraper.map_signals(fetch(vid)))
        session.add(video)
        session.commit()

    med = {b.channel_id: b.median_views for b in brain.channel_baselines(session)}.get(
        video.channel_id, 0.0
    )
    if med > 0 and video.views > 0:
        mult = round(video.views / med, 2)
        item.actual_multiplier = mult
        item.performed = mult >= VIRAL_THRESHOLD
        item.reward = mult  # realized outlier = the reward magnitude
        item.status = ContentStatus.scored
        session.add(
            ContentFeedback(
                item_id=item.id,
                kind=FeedbackKind.performance,
                reason=f'"{item.title}": actual {mult}x vs predicted {item.predicted_score}',
            )
        )
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def mark_published(
    session: Session,
    item_id: int,
    *,
    url: str,
    video_id: str | None = None,
    fetcher=None,
) -> ContentItem:
    """Attach the real published video, scrape it, and measure performance."""
    item = _require_item(session, item_id)
    vid = video_id or _video_id_from_url(url)
    if not vid:
        raise ValueError(f"could not extract a YouTube video id from URL: {url!r}")
    item.published_video_id = vid
    item.published_url = url
    item.published_at = datetime.utcnow()
    item.status = ContentStatus.published
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    return _measure(session, item, fetcher=fetcher)


def rescore(session: Session, *, fetcher=None) -> int:
    """Re-measure every published-but-not-yet-scored item (views accrue over time)."""
    pending = session.exec(
        select(ContentItem).where(ContentItem.status == ContentStatus.published)
    ).all()
    for item in pending:
        try:
            _measure(session, item, fetcher=fetcher)
        except Exception as exc:  # pragma: no cover - best-effort
            log.warning("rescore failed for item %s: %s", item.id, exc)
    return len(pending)


def _require_item(session: Session, item_id: int) -> ContentItem:
    item = session.get(ContentItem, item_id)
    if item is None:
        raise ValueError(f"content item {item_id} not found")
    return item
