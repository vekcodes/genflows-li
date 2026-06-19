"""Cron endpoints — the serverless replacement for APScheduler.

On Vercel there is no resident process, so the periodic jobs (incremental re-scrape,
transcript autofill, weekly content batch, daily rescore) are exposed as endpoints that
Vercel Cron invokes on a schedule (see vercel.json `crons`). They also work anywhere else
(curl / Task Scheduler) — each call does one bounded unit of work.

Auth: when the CRON_SECRET env var is set, Vercel sends `Authorization: Bearer <CRON_SECRET>`
automatically and we require it. Otherwise the regular BRAIN_API_KEY (x-api-key) applies if
configured; with neither set the endpoints are open (local dev).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..models import ContentRun, IngestStatus

log = logging.getLogger("brain.cron")

router = APIRouter(prefix="/cron", tags=["cron"])


def _authorize(request: Request) -> None:
    secret = os.environ.get("CRON_SECRET")
    if secret:
        if request.headers.get("authorization") == f"Bearer {secret}":
            return
        raise HTTPException(401, "invalid or missing cron secret")
    key = get_settings().api_key
    if key and request.headers.get("x-api-key") != key:
        raise HTTPException(401, "invalid or missing API key")


@router.get("/scrape-tick")
def scrape_tick(request: Request, session: Session = Depends(get_session)) -> dict:
    """Re-ingest any source past its cadence (new posts only)."""
    _authorize(request)
    from .. import scheduler

    scheduler._tick()
    return {"status": "ok"}


@router.get("/weekly-content")
def weekly_content(
    request: Request,
    n: int | None = None,
    refresh: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    """Generate the weekly batch. Default refresh=False — /cron/scrape-tick owns scraping,
    and the whole call must fit in the platform's maxDuration (keep n small on Vercel)."""
    _authorize(request)
    from .. import agent

    batch_id = uuid.uuid4().hex[:12]
    profile = agent.get_profile(session)
    count = n or profile.n_per_week
    run = ContentRun(batch_id=batch_id, status=IngestStatus.running, n_requested=count)
    session.add(run)
    session.commit()
    try:
        agent.generate_batch(session, n=count, batch_id=batch_id, run=run, refresh=refresh)
        run.status = IngestStatus.done
        run.message = f"{run.n_done}/{run.n_requested} produced"
    except Exception as exc:  # noqa: BLE001 - surfaced on the run row
        run.status = IngestStatus.error
        run.message = str(exc)
        log.exception("cron weekly content batch failed")
    finally:
        run.finished_at = datetime.utcnow()
        session.add(run)
        session.commit()
    return {"batch_id": batch_id, "status": run.status, "message": run.message}


@router.get("/daily-rescore")
def daily_rescore(request: Request, session: Session = Depends(get_session)) -> dict:
    """Re-measure published items as their reaction counts accrue."""
    _authorize(request)
    from .. import agent

    return {"status": "ok", "rescored": agent.rescore(session)}
