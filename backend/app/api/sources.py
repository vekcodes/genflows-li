"""Layer A: sources registry CRUD + scrape queue.

Adding a channel enqueues a scrape job (handled by the single-worker `scrape_queue`), so the
request returns immediately and the UI can watch progress. Scrapes never overlap.
"""
from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..db import engine, get_session
from ..ingestion import transcripts as transcripts_mod
from ..models import IngestRun, IngestStatus, Source, SourceKind
from ..schemas import ScrapeJobRead, SourceCreate, SourceRead
from ..scrape_queue import enqueue_source

router = APIRouter(prefix="/sources", tags=["sources"])


def _guess_kind(url: str) -> SourceKind:
    if "list=" in url:
        return SourceKind.playlist
    if "watch?v=" in url or "youtu.be/" in url or "/shorts/" in url:
        return SourceKind.video
    return SourceKind.channel


@router.get("", response_model=list[SourceRead])
def list_sources(session: Session = Depends(get_session)) -> list[Source]:
    return list(session.exec(select(Source).order_by(Source.created_at.desc())).all())


@router.post("", response_model=SourceRead, status_code=201)
def create_source(
    body: SourceCreate,
    ingest: bool = True,
    session: Session = Depends(get_session),
) -> Source:
    source = Source(
        url=body.url,
        kind=_guess_kind(body.url),
        niche=body.niche,
        cadence_hours=body.cadence_hours,
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    if ingest:
        enqueue_source(session, source.id)  # queued scrape (recent + popular videos)
    return source


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: int, session: Session = Depends(get_session)) -> None:
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(404, "source not found")
    session.delete(source)
    session.commit()


@router.post("/{source_id}/ingest", response_model=ScrapeJobRead)
def ingest_now(source_id: int, session: Session = Depends(get_session)):
    """Queue a (re)scrape for one source; returns the queued job."""
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(404, "source not found")
    run = enqueue_source(session, source_id)
    return _job(run, source)


def _retry_transcripts_bg(run_id: int, channel_id: str | None, limit: int) -> None:
    with Session(engine) as session:
        run = session.get(IngestRun, run_id)
        if run is None:
            return

        def cb(done: int, total: int, msg: str) -> None:
            run.scrape_done, run.scrape_total, run.message = done, total, msg
            session.add(run)
            session.commit()

        try:
            run.status = IngestStatus.running
            session.add(run)
            session.commit()
            res = transcripts_mod.backfill_missing(
                session, channel_id=channel_id, limit=limit, on_progress=cb
            )
            run.status = IngestStatus.done
            run.new_videos = res["fetched"]
            if res["blocked"]:
                run.message = (
                    f"YouTube IP-blocked — fetched {res['fetched']} before the block. "
                    "Try later or set BRAIN_TRANSCRIPT_PROXY."
                )
            else:
                run.message = f"{res['fetched']} transcripts fetched · {res['unavailable']} have no captions"
        except Exception as exc:  # noqa: BLE001
            run.status = IngestStatus.error
            run.message = str(exc)
        finally:
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()


@router.post("/{source_id}/transcripts", response_model=ScrapeJobRead)
def retry_transcripts(source_id: int, limit: int = 300, session: Session = Depends(get_session)):
    """Re-fetch only the missing transcripts for a source (no re-scraping). Shows in the queue."""
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(404, "source not found")
    run = IngestRun(
        source_id=source_id, kind="transcripts", status=IngestStatus.queued, message="retrying transcripts"
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    if get_settings().serverless:
        _retry_transcripts_bg(run.id, source.external_id, limit)  # in-request (no bg threads)
        session.refresh(run)
    else:
        threading.Thread(
            target=_retry_transcripts_bg, args=(run.id, source.external_id, limit), daemon=True
        ).start()
    return _job(run, source)


@router.get("/queue", response_model=list[ScrapeJobRead])
def scrape_queue(limit: int = 20, session: Session = Depends(get_session)):
    """Recent + active scrape jobs with live progress (for the queue UI)."""
    runs = session.exec(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit)).all()
    sources = {s.id: s for s in session.exec(select(Source)).all()}
    return [_job(r, sources.get(r.source_id)) for r in runs]


def _job(run: IngestRun, source: Source | None) -> ScrapeJobRead:
    return ScrapeJobRead(
        id=run.id,
        source_id=run.source_id,
        source_title=(source.title or source.url) if source else None,
        source_url=source.url if source else None,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        scrape_total=run.scrape_total,
        scrape_done=run.scrape_done,
        new_videos=run.new_videos,
        message=run.message,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )
