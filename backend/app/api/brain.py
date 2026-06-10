"""Layer F: Brain API — what consumer tools call.

Implemented now (pure analytics over the Raw Lake): baselines + outlier scoring.
Stubbed (501 until an LLM provider is configured): pattern / pain-point / style
mining and idea ranking — these are the LLM-powered insight producers.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from .. import brain, demand, insights, vectorstore, virality
from ..config import get_settings
from ..db import get_session
from ..llm.base import LLMError
from ..llm.factory import get_llm
from ..models import Comment, Source, Transcript, Video
from ..schemas import BaselineRead, LLMStatus, OutlierRead

router = APIRouter(prefix="/brain", tags=["brain"])


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    llm = get_llm()
    s = get_settings()
    return {
        "sources": session.exec(select(func.count()).select_from(Source)).one(),
        "videos": session.exec(select(func.count()).select_from(Video)).one(),
        "transcripts": session.exec(select(func.count()).select_from(Transcript)).one(),
        "comments": session.exec(select(func.count()).select_from(Comment)).one(),
        "llm": LLMStatus(
            provider=llm.name if llm else None,
            available=bool(llm and llm.available()),
        ).model_dump(),
        "scheduler": {
            "enabled": s.scheduler_enabled,
            "cadence_hours": s.default_cadence_hours,
            "interval_minutes": s.scheduler_interval_minutes,
        },
    }


@router.get("/baselines", response_model=list[BaselineRead])
def baselines(session: Session = Depends(get_session)):
    return brain.channel_baselines(session)


@router.get("/outliers", response_model=list[OutlierRead])
def outliers(
    min_multiplier: float = 1.0,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    return brain.outliers(session, min_multiplier=min_multiplier, limit=limit)


@router.get("/trending")
def trending(
    days_window: int = 180, limit: int = 12, session: Session = Depends(get_session)
) -> list[dict]:
    """What's hot now: recent videos ranked by velocity (views ÷ days since publish)."""
    from dataclasses import asdict

    return [asdict(t) for t in brain.trending(session, days_window=days_window, limit=limit)]


# --- ★ Virality model + backtester ---


@router.get("/virality/backtest")
def virality_backtest(
    viral_threshold: float = 3.0,
    test_frac: float = 0.3,
    session: Session = Depends(get_session),
) -> dict:
    """Time-split backtest of the virality predictor on held-out history."""
    return virality.backtest(session, threshold=viral_threshold, test_frac=test_frac)


@router.get("/virality/score")
def virality_score(
    title: str,
    duration_sec: int = 0,
    viral_threshold: float = 3.0,
    session: Session = Depends(get_session),
) -> dict:
    """Predicted virality (0-100) for a candidate title + its nearest proven analogs."""
    return virality.score(
        session, title=title, duration_sec=duration_sec, threshold=viral_threshold
    )


# --- Mined insights (LLM-powered) ---
# GET endpoints just read stored Brain state (no LLM needed).
# POST /mine/* run the Claude-powered mining and persist results.


@router.get("/pain-points")
def get_pain_points(niche: str | None = None, session: Session = Depends(get_session)):
    return insights.list_pain_points(session, niche)


@router.get("/patterns")
def get_patterns(niche: str | None = None, session: Session = Depends(get_session)):
    return insights.list_patterns(session, niche)


@router.get("/style-cards")
def get_style_cards(session: Session = Depends(get_session)):
    return insights.list_style_cards(session)


def _run_llm(fn):
    try:
        return fn()
    except LLMError as exc:
        raise HTTPException(501, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/mine/pain-points")
def mine_pain_points(niche: str | None = None, k: int = 12, session: Session = Depends(get_session)):
    return _run_llm(lambda: insights.mine_pain_points(session, niche=niche, k=k))


@router.post("/mine/patterns")
def mine_patterns(
    niche: str | None = None, min_multiplier: float = 3.0, session: Session = Depends(get_session)
):
    return _run_llm(lambda: insights.mine_patterns(session, niche=niche, min_multiplier=min_multiplier))


@router.post("/mine/style-card")
def mine_style_card(channel_id: str, session: Session = Depends(get_session)):
    card = _run_llm(lambda: insights.mine_style_card(session, channel_id=channel_id))
    if card is None:
        raise HTTPException(404, "no transcripts found for that channel")
    return card


# --- Market demand (external, free) + semantic search (local vector index) ---


@router.get("/content-gaps")
def content_gaps(niche: str | None = None, session: Session = Depends(get_session)) -> list[dict]:
    """Audience pain-points barely covered by existing content = best next videos."""
    return brain.content_gaps(session, niche=niche)


@router.get("/demand")
def validate_demand(keyword: str) -> dict:
    """Google Trends direction + YouTube search-suggest for a keyword."""
    return demand.validate_demand(keyword)


@router.get("/search")
def semantic_search(q: str, k: int = 8, session: Session = Depends(get_session)) -> list[dict]:
    """Top transcript chunks relevant to a query (RAG over the brain)."""
    return vectorstore.search(session, q, k=k)


# --- Brain Wiki (qualitative knowledge layer, opt-in) ---


@router.get("/wiki/status")
def wiki_status(session: Session = Depends(get_session)) -> dict:
    """Page counts in the Brain Wiki (or `enabled: false` when the flag is off)."""
    if not get_settings().brain_wiki_enabled:
        return {"enabled": False}
    from .. import wiki
    from ..wiki import read as wiki_read

    store = wiki.default_store()
    return {"enabled": True, "dir": str(store.root), "pages": wiki_read.counts(store)}


@router.post("/wiki/backfill")
def wiki_backfill(limit: int = 10, session: Session = Depends(get_session)) -> dict:
    """Populate the wiki from videos already in the Raw Lake (capped), no re-scraping."""
    if not get_settings().brain_wiki_enabled:
        raise HTTPException(409, "Brain Wiki disabled — set BRAIN_BRAIN_WIKI_ENABLED=true")
    from datetime import date

    from .. import wiki

    store = wiki.default_store()
    results = _run_llm(lambda: wiki.backfill(session, store, today=date.today(), limit=limit))
    return {
        "ingested": len(results),
        "videos": [
            {"video_id": r.video_id, "multiplier": r.multiplier, "pages": len(r.pages_touched)}
            for r in results
        ],
    }
