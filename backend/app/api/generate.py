"""Layer G API: the YouTube Script Writer endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..db import get_session
from ..generation import ideas as ideas_gen
from ..generation import script as script_gen
from ..llm.base import LLMError

router = APIRouter(prefix="/generate", tags=["generate"])


class IdeasRequest(BaseModel):
    channel_id: str | None = None
    niche: str | None = None
    n: int = 8
    duration_sec: int = 600
    min_score: float = 0.0  # virality gate: drop ideas below this (0-100)
    top: int | None = None
    viral_threshold: float = 3.0


class ScriptRequest(BaseModel):
    title: str
    angle: str = ""
    channel_id: str | None = None
    polish: bool = True


def _run_llm(fn):
    try:
        return fn()
    except LLMError as exc:
        raise HTTPException(501, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/ideas")
def generate_ideas(body: IdeasRequest, session: Session = Depends(get_session)) -> dict:
    """Evidence-ranked ideas, each scored + gated by the backtested virality model."""
    return _run_llm(lambda: ideas_gen.generate_ideas(
        session,
        channel_id=body.channel_id,
        niche=body.niche,
        n=body.n,
        duration_sec=body.duration_sec,
        min_score=body.min_score,
        top=body.top,
        viral_threshold=body.viral_threshold,
    ))


@router.post("/script")
def generate_script(body: ScriptRequest, session: Session = Depends(get_session)) -> dict:
    """Outline → section-wise expand → polish for a chosen idea."""
    return _run_llm(lambda: script_gen.generate_script(
        session,
        title=body.title,
        angle=body.angle,
        channel_id=body.channel_id,
        polish=body.polish,
    ))
