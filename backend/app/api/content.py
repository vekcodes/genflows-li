"""Layer G API — the agentic content engine: durable queue / calendar + review actions.

Generation is long-running, so batch generation and decline-regeneration run in daemon threads
(each with its own DB session, mirroring app/api/sources.py), and the client polls the queue.
The backtested virality model stays the gate inside `agent` / `refine.craft`.
"""
from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import agent
from ..config import get_settings
from ..db import engine, get_session
from ..llm.base import LLMError
from ..models import ContentItem, ContentRun, ContentStatus, IngestStatus
from ..schemas import (
    ContentItemRead,
    ContentRunRead,
    CreatorProfileRead,
    CreatorProfileUpdate,
    DeclineRequest,
    PublishRequest,
    ScheduleRequest,
)

router = APIRouter(prefix="/content", tags=["content"])


def _run_llm(fn):
    try:
        return fn()
    except LLMError as exc:
        raise HTTPException(501, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---- Queue / calendar ----


@router.get("/queue", response_model=list[ContentItemRead])
def queue(status: ContentStatus | None = None, session: Session = Depends(get_session)):
    q = select(ContentItem).order_by(ContentItem.created_at.desc())
    if status is not None:
        q = q.where(ContentItem.status == status)
    return list(session.exec(q).all())


# ---- Generation (async batch) ----


def _generate_batch_bg(batch_id: str, n: int, topic: str | None, refresh: bool) -> None:
    with Session(engine) as session:
        run = session.exec(select(ContentRun).where(ContentRun.batch_id == batch_id)).first()
        try:
            agent.generate_batch(session, n=n, batch_id=batch_id, run=run, refresh=refresh, topic=topic)
            if run:
                run.status = IngestStatus.done
                run.message = f"{run.n_done}/{run.n_requested} produced"
        except Exception as exc:  # noqa: BLE001
            if run:
                run.status = IngestStatus.error
                run.message = str(exc)
        finally:
            if run:
                from datetime import datetime

                run.finished_at = datetime.utcnow()
                session.add(run)
                session.commit()


@router.post("/generate")
def generate(
    n: int | None = None,
    topic: str | None = None,
    refresh: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    """Kick off generation in the background. Poll /content/runs/{batch_id} + /content/queue.

    Weekly batch: no topic, refresh=True. On command: a topic, refresh=False (skip re-scrape).
    """
    profile = agent.get_profile(session)
    count = n or profile.n_per_week
    batch_id = uuid.uuid4().hex[:12]
    run = ContentRun(batch_id=batch_id, status=IngestStatus.running, n_requested=count)
    session.add(run)
    session.commit()
    if get_settings().serverless:
        # No background threads on serverless: generate within this request (bounded by the
        # platform's maxDuration — keep n small and refresh=False there).
        _generate_batch_bg(batch_id, count, topic, refresh)
        return {"batch_id": batch_id, "n_requested": count}
    threading.Thread(
        target=_generate_batch_bg, args=(batch_id, count, topic, refresh), daemon=True
    ).start()
    return {"batch_id": batch_id, "n_requested": count}


@router.get("/runs/{batch_id}", response_model=ContentRunRead)
def get_run(batch_id: str, session: Session = Depends(get_session)):
    run = session.exec(select(ContentRun).where(ContentRun.batch_id == batch_id)).first()
    if run is None:
        raise HTTPException(404, "batch not found")
    return run


# ---- Review actions ----


@router.post("/{item_id}/approve", response_model=ContentItemRead)
def approve(item_id: int, session: Session = Depends(get_session)):
    return _run_llm(lambda: agent.approve(session, item_id))


@router.post("/{item_id}/schedule", response_model=ContentItemRead)
def schedule(item_id: int, body: ScheduleRequest, session: Session = Depends(get_session)):
    return _run_llm(lambda: agent.schedule(session, item_id, body.when))


def _regenerate_bg(item_id: int) -> None:
    with Session(engine) as session:
        try:
            agent.regenerate_from(session, item_id)
        except Exception:  # noqa: BLE001 - best-effort; surfaced via the queue
            pass


@router.post("/{item_id}/decline", response_model=ContentItemRead)
def decline(item_id: int, body: DeclineRequest, session: Session = Depends(get_session)):
    """Decline with a reason (returns the declined item); a replacement is generated in the background."""
    item = _run_llm(lambda: agent.mark_declined(session, item_id, body.reason))
    if get_settings().serverless:
        _regenerate_bg(item_id)  # in-request: one item fits comfortably in maxDuration
    else:
        threading.Thread(target=_regenerate_bg, args=(item_id,), daemon=True).start()
    return item


@router.post("/{item_id}/publish", response_model=ContentItemRead)
def publish(item_id: int, body: PublishRequest, session: Session = Depends(get_session)):
    return _run_llm(lambda: agent.mark_published(session, item_id, url=body.url))


@router.post("/rescore")
def rescore(session: Session = Depends(get_session)) -> dict:
    return {"updated": agent.rescore(session)}


# ---- Settings (CreatorProfile) ----


@router.get("/profile", response_model=CreatorProfileRead)
def get_profile(session: Session = Depends(get_session)):
    return agent.get_profile(session)


@router.put("/profile", response_model=CreatorProfileRead)
def update_profile(body: CreatorProfileUpdate, session: Session = Depends(get_session)):
    from datetime import datetime

    profile = agent.get_profile(session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    profile.updated_at = datetime.utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


# ---- Single item (parameterized — registered AFTER literal routes like /profile, /runs) ----


@router.get("/{item_id}", response_model=ContentItemRead)
def get_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(404, "content item not found")
    return item
