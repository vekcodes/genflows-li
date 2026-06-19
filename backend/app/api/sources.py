"""Layer A: sources registry CRUD + scrape queue — LinkedIn edition."""
from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import IngestRun, IngestStatus, Source, SourceKind
from ..schemas import ScrapeJobRead, SourceCreate, SourceRead
from ..scrape_queue import enqueue_source

router = APIRouter(prefix="/sources", tags=["sources"])


def _guess_kind(url: str) -> SourceKind:
    if "/company/" in url or "/showcase/" in url:
        return SourceKind.company
    if "/hashtag/" in url:
        return SourceKind.hashtag
    return SourceKind.profile


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
        enqueue_source(session, source.id)
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
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(404, "source not found")
    run = enqueue_source(session, source_id)
    return _job(run, source)


@router.get("/queue", response_model=list[ScrapeJobRead])
def scrape_queue(limit: int = 20, session: Session = Depends(get_session)):
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
