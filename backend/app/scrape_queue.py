"""Single-worker scrape queue — channels you add are scraped one at a time, with live progress.

Each queued scrape is an `IngestRun` row (status queued → running → done/error) whose
`scrape_done`/`scrape_total` drive a progress bar. One daemon worker means scrapes never overlap
(politeness for the residential IP). Queue state survives restarts: it lives in the IngestRun
rows, which `resume_pending()` re-enqueues on startup.
"""
from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime

from sqlmodel import Session, col, select

from .config import get_settings
from .db import engine
from .ingestion.pipeline import ingest_source
from .models import IngestRun, IngestStatus, Source

log = logging.getLogger("brain.scrapequeue")

_q: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def enqueue_source(session: Session, source_id: int) -> IngestRun:
    """Create a queued scrape job for a source and hand it to the worker.

    Serverless: there is no worker thread to hand off to (the process freezes after the
    response), so the scrape runs synchronously inside this request — bounded by the
    platform's maxDuration. Incremental re-scrapes are small; do initial backfills locally.
    """
    run = IngestRun(source_id=source_id, status=IngestStatus.queued, message="queued")
    session.add(run)
    session.commit()
    session.refresh(run)
    if get_settings().serverless:
        _process(run.id)
        session.refresh(run)
        return run
    start_worker()
    _q.put(run.id)
    return run


def _process(run_id: int) -> None:
    settings = get_settings()
    with Session(engine) as session:
        run = session.get(IngestRun, run_id)
        if run is None or run.status in (IngestStatus.done, IngestStatus.error):
            return
        source = session.get(Source, run.source_id)
        if source is None:
            run.status = IngestStatus.error
            run.message = "source was removed"
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()
            return
        try:
            ingest_source(
                session,
                source,
                max_new=settings.agent_max_videos_per_source,
                popular_k=settings.agent_popular_per_source,
                comment_limit=settings.comment_limit,
                cap=True,
                run=run,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced on the run row
            log.exception("scrape failed for source %s", run.source_id)
            run.status = IngestStatus.error
            run.message = str(exc)
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()


def _loop() -> None:
    while True:
        run_id = _q.get()
        try:
            _process(run_id)
        except Exception:  # noqa: BLE001 - never let the worker die
            log.exception("scrape worker error on run %s", run_id)
        finally:
            _q.task_done()


def start_worker() -> None:
    """Ensure the single worker thread is running (idempotent)."""
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_loop, daemon=True, name="scrape-worker")
        _worker.start()


def resume_pending() -> None:
    """Re-enqueue scrapes left queued/running by a previous process (call once at startup)."""
    start_worker()
    with Session(engine) as session:
        leftovers = session.exec(
            select(IngestRun).where(
                col(IngestRun.status).in_([IngestStatus.queued, IngestStatus.running])
            )
        ).all()
        resumed = 0
        for r in leftovers:
            if r.kind == "scrape":
                r.status = IngestStatus.queued  # interrupted mid-run → requeue from scratch
                session.add(r)
                _q.put(r.id)
                resumed += 1
            else:
                # Transcript backfills aren't re-run here — the scheduler autofill drains the
                # remaining missing transcripts. Just clear the stale 'running' so it can't zombie.
                r.status = IngestStatus.error
                r.message = (r.message or "") + " (interrupted; autofill continues)"
                session.add(r)
        if leftovers:
            session.commit()
            log.info("resume: re-enqueued %s scrape(s), retired %s stale job(s)", resumed, len(leftovers) - resumed)
