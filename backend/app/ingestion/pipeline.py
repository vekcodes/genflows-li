"""Orchestrates one ingest pass for a LinkedIn source (Layer B → Layer C).

Incremental by design: fetch posts from the source, then write only posts
not already in the Raw Lake. Comments fetched per post as configured.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from sqlmodel import Session, select

from ..config import get_settings
from ..models import IngestRun, IngestStatus, LinkedInPost, PostComment, Source
from ..throttle import jittered_delay, with_retries
from . import resolver, scraper

log = logging.getLogger("brain.ingest")

ProgressFn = Callable[[int, int, str], None]


def _existing_post_ids(session: Session) -> set[str]:
    return set(session.exec(select(LinkedInPost.id)).all())


def ingest_source(
    session: Session,
    source: Source,
    *,
    max_new: int | None = None,
    with_comments: bool = True,
    comment_limit: int | None = None,
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
        source.external_id = source.external_id or resolved.external_id
        source.kind = resolved.kind
        if resolved.title and not source.title:
            source.title = resolved.title

        known = _existing_post_ids(session)
        limit = max_new or settings.agent_max_videos_per_source

        _progress(0, limit, f"fetching up to {limit} posts from {source.url}")

        fetch_comments = with_comments and comment_limit > 0
        posts = with_retries(
            lambda: scraper.fetch_posts(
                source.url,
                resolved.kind,
                limit=limit,
                with_comments=fetch_comments,
                comment_limit=comment_limit,
            ),
            retries=settings.scrape_max_retries,
            base_delay=settings.scrape_backoff_base_sec,
        )

        new_posts = [p for p in posts if p["id"] not in known]
        total = len(new_posts)
        _progress(0, total, f"{total} new post(s) to ingest")

        ingested = 0
        for post in new_posts:
            try:
                signals = scraper.map_signals(post)
                db_post = LinkedInPost(source_id=source.id, **signals)
                session.add(db_post)
                for c in scraper.map_comments(post, comment_limit):
                    session.add(PostComment(post_id=post["id"], **c))
                session.commit()
                ingested += 1
                _progress(ingested, total, f"ingested {ingested}/{total}")
                jittered_delay(settings.scrape_min_delay_sec, settings.scrape_max_delay_sec)
            except Exception as exc:
                session.rollback()
                log.warning("post %s failed: %s", post.get("id"), exc)

        # Backfill title from the first post's author name if we don't have one yet.
        if not source.title and posts:
            source.title = posts[0].get("author_name") or resolved.external_id

        source.last_scraped_at = datetime.utcnow()
        session.add(source)
        run.status = IngestStatus.done
        run.new_videos = ingested
        run.message = f"fetched {len(posts)} posts, ingested {ingested} new"

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
