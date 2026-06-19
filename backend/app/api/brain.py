"""Layer F: Brain API — what consumer tools call.

LinkedIn edition: baselines + outlier scoring (reactions ÷ author median),
plus LLM-powered pattern/pain-point/style mining.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from .. import brain, demand, insights, virality
from ..config import get_settings
from ..db import get_session
from ..llm.base import LLMError
from ..llm.factory import get_llm
from ..models import LinkedInPost, PostComment, Source
from ..schemas import BaselineRead, LLMStatus, OutlierRead

router = APIRouter(prefix="/brain", tags=["brain"])


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    llm = get_llm()
    s = get_settings()
    return {
        "sources": session.exec(select(func.count()).select_from(Source)).one(),
        "videos": session.exec(select(func.count()).select_from(LinkedInPost)).one(),
        "transcripts": 0,   # kept for frontend schema compat
        "comments": session.exec(select(func.count()).select_from(PostComment)).one(),
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
    days_window: int = 90, limit: int = 12, session: Session = Depends(get_session)
) -> list[dict]:
    from dataclasses import asdict
    return [asdict(t) for t in brain.trending(session, days_window=days_window, limit=limit)]


@router.get("/virality/backtest")
def virality_backtest(
    viral_threshold: float = 2.0,
    test_frac: float = 0.3,
    session: Session = Depends(get_session),
) -> dict:
    return virality.backtest(session, threshold=viral_threshold, test_frac=test_frac)


@router.get("/virality/score")
def virality_score(
    title: str,
    duration_sec: int = 0,
    viral_threshold: float = 2.0,
    session: Session = Depends(get_session),
) -> dict:
    return virality.score(session, title=title, threshold=viral_threshold)


def _run_llm(fn):
    try:
        return fn()
    except LLMError as exc:
        raise HTTPException(501, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/pain-points")
def get_pain_points(niche: str | None = None, session: Session = Depends(get_session)):
    return insights.list_pain_points(session, niche)


@router.get("/patterns")
def get_patterns(niche: str | None = None, session: Session = Depends(get_session)):
    return insights.list_patterns(session, niche)


@router.get("/style-cards")
def get_style_cards(session: Session = Depends(get_session)):
    return insights.list_style_cards(session)


@router.post("/mine/pain-points")
def mine_pain_points(niche: str | None = None, k: int = 12, session: Session = Depends(get_session)):
    return _run_llm(lambda: insights.mine_pain_points(session, niche=niche, k=k))


@router.post("/mine/patterns")
def mine_patterns(
    niche: str | None = None, min_multiplier: float = 2.0, session: Session = Depends(get_session)
):
    return _run_llm(lambda: insights.mine_patterns(session, niche=niche, min_multiplier=min_multiplier))


@router.post("/mine/style-card")
def mine_style_card(channel_id: str, session: Session = Depends(get_session)):
    card = _run_llm(lambda: insights.mine_style_card(session, channel_id=channel_id))
    if card is None:
        raise HTTPException(404, "no posts found for that author")
    return card


@router.get("/content-gaps")
def content_gaps(niche: str | None = None, session: Session = Depends(get_session)) -> list[dict]:
    return brain.content_gaps(session, niche=niche)


@router.get("/demand")
def validate_demand(keyword: str) -> dict:
    """Google Trends direction + search-suggest for a LinkedIn topic keyword."""
    return demand.validate_demand(keyword)


@router.get("/search")
def semantic_search(q: str, k: int = 8, session: Session = Depends(get_session)) -> list[dict]:
    """Keyword search over ingested post text."""
    from sqlmodel import select as _select
    from ..models import LinkedInPost as _Post
    posts = session.exec(
        _select(_Post)
        .where(_Post.text.contains(q))
        .limit(k)
    ).all()
    return [
        {"video_id": p.id, "idx": 0, "score": 1.0,
         "text": p.text[:300].replace("\n", " ")}
        for p in posts
    ]
