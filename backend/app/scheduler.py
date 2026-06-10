"""Continuous, incremental re-check of active sources (the self-update loop).

Opt-in via BRAIN_SCHEDULER_ENABLED=true. Every tick, any active source whose
last scrape is older than its cadence gets re-ingested (new videos only).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from .config import get_settings
from .db import engine
from .ingestion.pipeline import ingest_source
from .models import Source

log = logging.getLogger("brain.scheduler")
_scheduler: BackgroundScheduler | None = None


def _due(source: Source, now: datetime) -> bool:
    if not source.active:
        return False
    if source.last_scraped_at is None:
        return True
    return now - source.last_scraped_at >= timedelta(hours=source.cadence_hours)


def _tick() -> None:
    now = datetime.utcnow()
    with Session(engine) as session:
        sources = session.exec(select(Source).where(Source.active == True)).all()  # noqa: E712
        for source in sources:
            if _due(source, now):
                log.info("re-ingesting source %s (%s)", source.id, source.url)
                ingest_source(session, source)


def _weekly_content() -> None:
    """The autonomous creator: generate this week's content batch into the queue."""
    from . import agent
    from .models import ContentRun, IngestStatus

    import uuid

    batch_id = uuid.uuid4().hex[:12]
    with Session(engine) as session:
        run = ContentRun(batch_id=batch_id, status=IngestStatus.running)
        profile = agent.get_profile(session)
        run.n_requested = profile.n_per_week
        session.add(run)
        session.commit()
        try:
            agent.generate_batch(session, batch_id=batch_id, run=run)
            run.status = IngestStatus.done
            run.message = f"{run.n_done}/{run.n_requested} produced"
        except Exception as exc:  # noqa: BLE001
            run.status = IngestStatus.error
            run.message = str(exc)
            log.exception("weekly content batch failed")
        finally:
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()
    log.info("weekly content batch %s: %s", batch_id, run.message)


def _daily_rescore() -> None:
    """Re-measure published items as their view counts accrue."""
    from . import agent

    with Session(engine) as session:
        n = agent.rescore(session)
    log.info("rescored %s published item(s)", n)


def _transcript_autofill() -> None:
    """Backfill a bounded number of missing transcripts each tick (captions → Whisper)."""
    from .config import get_settings
    from .ingestion import transcripts

    settings = get_settings()
    if not settings.transcript_autofill_enabled:
        return
    with Session(engine) as session:
        res = transcripts.backfill_missing(session, limit=settings.transcript_autofill_per_tick)
    if res["total"]:
        log.info("transcript autofill: %s fetched, %s unavailable", res["fetched"], res["unavailable"])


def start_scheduler(interval_minutes: int | None = None) -> None:
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    minutes = interval_minutes or settings.scheduler_interval_minutes
    _scheduler = BackgroundScheduler(daemon=True)
    # max_instances=1 + coalesce: a long scrape never overlaps the next tick.
    _scheduler.add_job(
        _tick, "interval", minutes=minutes, id="recheck", max_instances=1, coalesce=True
    )
    if settings.transcript_autofill_enabled:
        # Drains missing transcripts a few at a time (restart-safe; never hogs the CPU).
        _scheduler.add_job(
            _transcript_autofill, "interval", minutes=settings.transcript_autofill_interval_minutes,
            id="transcript_autofill", max_instances=1, coalesce=True,
        )
        log.info(
            "transcript autofill on — %s every %smin",
            settings.transcript_autofill_per_tick, settings.transcript_autofill_interval_minutes,
        )
    if settings.agent_enabled:
        _scheduler.add_job(
            _weekly_content, "cron", day_of_week=settings.agent_weekly_day,
            hour=settings.agent_weekly_hour, id="weekly_content", max_instances=1, coalesce=True,
        )
        _scheduler.add_job(
            _daily_rescore, "cron", hour=settings.agent_rescore_hour,
            id="daily_rescore", max_instances=1, coalesce=True,
        )
        log.info(
            "agent enabled — weekly batch on day %s @ %sh, rescore daily @ %sh",
            settings.agent_weekly_day, settings.agent_weekly_hour, settings.agent_rescore_hour,
        )
    _scheduler.start()
    log.info("scheduler started (every %s min)", minutes)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
