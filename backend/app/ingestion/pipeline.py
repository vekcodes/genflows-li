"""Orchestrates one ingest pass for a source (Layer B → Layer C).

Incremental by design: resolve the source's video ids, then fetch full signals
+ transcript + comments only for videos not already in the Raw Lake.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from sqlmodel import Session, select

from ..config import get_settings
from ..models import Comment, IngestRun, IngestStatus, Source, Transcript, Video
from ..throttle import jittered_delay, scrape_limiter, with_retries
from .. import vectorstore
from . import resolver, scraper, transcripts

log = logging.getLogger("brain.ingest")

# (scraped_so_far, total_to_scrape, message) — reported after resolve and each video.
ProgressFn = Callable[[int, int, str], None]


def _existing_video_ids(session: Session) -> set[str]:
    return set(session.exec(select(Video.id)).all())


def _prescan_views(ids: list[str], *, settings, report: ProgressFn) -> dict[str, int]:
    """Fetch metadata-only (no comments) for ids to learn their view counts → rank popularity.

    YouTube hides view counts in the fast channel listing, so this lightweight pass is the only
    reliable way to find a channel's all-time hits without full-scraping everything.
    """
    n = len(ids)
    views: dict[str, int] = {}
    for i, vid in enumerate(ids):
        try:
            info = with_retries(
                lambda: scraper.fetch_video(vid, with_comments=False, comment_limit=0),
                retries=settings.scrape_max_retries,
                base_delay=settings.scrape_backoff_base_sec,
            )
            views[vid] = int(info.get("view_count") or 0)
        except Exception as exc:  # noqa: BLE001 - a failed probe just can't be ranked
            log.warning("popularity pre-scan failed for %s: %s", vid, exc)
            views[vid] = 0
        report(i + 1, n, f"finding popular videos… {i + 1}/{n} scanned")
        jittered_delay(0.0, settings.scrape_prescan_delay_sec)
    return views


def _select_new_ids(resolved, known: set[str], *, max_new, popular_k, settings, report) -> list[str]:
    """The N most-recent NEW videos plus the top-K most-popular ones (deduped, recent first)."""
    recent_pool = resolved.video_ids if max_new is None else resolved.video_ids[:max_new]
    recent = [v for v in recent_pool if v not in known]

    popular: list[str] = []
    if popular_k:
        recent_set = set(recent)
        older = [
            v
            for v in resolved.video_ids[(max_new or 0):]
            if v not in known and v not in recent_set
        ][: settings.popular_scan_cap]
        views = {v: resolved.video_views.get(v) for v in older}
        if older and all(views.get(v) is None for v in older):  # flat gave no views → pre-scan
            views = _prescan_views(older, settings=settings, report=report)
        ranked = sorted(
            (v for v in older if (views.get(v) or 0) > 0),
            key=lambda v: views[v] or 0,
            reverse=True,
        )
        popular = ranked[:popular_k]

    return list(dict.fromkeys([*recent, *popular]))  # preserve order, drop dups


def ingest_source(
    session: Session,
    source: Source,
    *,
    max_new: int | None = None,
    popular_k: int | None = None,
    with_comments: bool = True,
    comment_limit: int | None = None,
    cap: bool = True,
    on_progress: ProgressFn | None = None,
    run: IngestRun | None = None,
) -> IngestRun:
    settings = get_settings()
    comment_limit = settings.comment_limit if comment_limit is None else comment_limit
    report: ProgressFn = on_progress or (lambda _d, _t, _m: None)
    if run is None:
        run = IngestRun(source_id=source.id or 0, status=IngestStatus.running)
    else:
        run.status = IngestStatus.running
    session.add(run)
    session.commit()
    session.refresh(run)

    def _progress(done: int, total: int, msg: str) -> None:
        run.scrape_done = done
        run.scrape_total = total
        run.message = msg
        session.add(run)
        session.commit()
        report(done, total, msg)

    try:
        resolved = resolver.resolve(source.url)
        # Backfill resolved metadata onto the source row.
        source.external_id = source.external_id or resolved.external_id
        source.title = source.title or resolved.title
        source.kind = resolved.kind

        known = _existing_video_ids(session)
        new_ids = _select_new_ids(
            resolved, known, max_new=max_new, popular_k=popular_k, settings=settings, report=_progress
        )

        total = len(new_ids)
        _progress(0, total, f"{total} new video(s) to scrape")

        limiter = scrape_limiter()
        ingested = 0
        capped = False
        for vid in new_ids:
            # Global hourly politeness cap — stop the run, resume next tick.
            # `cap=False` (full-dump assistant runs) scrapes every video, relying on the
            # per-video jittered delay for politeness rather than truncating.
            if cap and not limiter.try_acquire():
                capped = True
                log.info("hourly scrape cap reached; stopping run with %s new", ingested)
                break
            try:
                fetch_comments = with_comments and comment_limit > 0
                info = with_retries(
                    lambda: scraper.fetch_video(
                        vid, with_comments=fetch_comments, comment_limit=comment_limit
                    ),
                    retries=settings.scrape_max_retries,
                    base_delay=settings.scrape_backoff_base_sec,
                )
                signals = scraper.map_signals(info)
                video = Video(source_id=source.id, **signals)

                tr = transcripts.fetch_transcript(vid)
                if tr is not None:
                    video.has_transcript = True
                    session.add(
                        Transcript(
                            video_id=vid,
                            lang=tr.lang,
                            provider=tr.provider,
                            text=tr.text,
                            segments_json=tr.segments_json,
                        )
                    )
                    # Chunk + index for semantic retrieval (local vector store).
                    vectorstore.index_video(session, vid, tr.text)

                session.add(video)
                for c in scraper.map_comments(info, comment_limit):
                    session.add(Comment(video_id=vid, **c))

                session.commit()
                ingested += 1
                _progress(ingested, total, f"scraped {ingested}/{total}")

                # Brain Wiki dual-write (opt-in). Never let it break ingestion.
                if settings.brain_wiki_enabled:
                    try:
                        from datetime import date
                        from .. import wiki

                        wiki.ingest_video(session, wiki.default_store(), vid, today=date.today())
                    except Exception as wexc:  # pragma: no cover - best-effort side layer
                        log.warning("brain-wiki ingest skipped for %s: %s", vid, wexc)

                # Polite pause between videos so we don't burst the IP.
                jittered_delay(settings.scrape_min_delay_sec, settings.scrape_max_delay_sec)
            except Exception as exc:  # one bad video shouldn't kill the run
                session.rollback()
                log.warning("video %s failed: %s", vid, exc)

        source.last_scraped_at = datetime.utcnow()
        session.add(source)
        run.status = IngestStatus.done
        run.new_videos = ingested
        tail = " (hourly cap hit — more remain)" if capped else ""
        run.message = f"resolved {len(resolved.video_ids)} ids, ingested {ingested} new{tail}"
    except Exception as exc:
        session.rollback()
        run.status = IngestStatus.error
        run.message = str(exc)
        log.exception("ingest_source failed for source %s", source.id)
    finally:
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
        session.refresh(run)

    return run
