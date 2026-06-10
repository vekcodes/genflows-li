"""The assistant endpoint: one request runs the whole pipeline as a background job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import assistant

router = APIRouter(prefix="/assistant", tags=["assistant"])


class RunRequest(BaseModel):
    channels: list[str] = []
    prompt: str = "Generate me some YouTube scripts."
    niche: str | None = None
    n_scripts: int = 3
    target_score: float = 60.0  # virality bar each idea must clear before writing
    offer: str | None = None  # what you sell + booking link → drives the description CTA


@router.post("/run")
def run(body: RunRequest) -> dict:
    channels = [c.strip() for c in body.channels if c.strip()]
    job = assistant.start(
        channels=channels,
        prompt=body.prompt,
        niche=body.niche,
        n_scripts=max(1, min(body.n_scripts, 6)),
        target_score=max(0.0, min(body.target_score, 100.0)),
        offer=body.offer,
    )
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    j = assistant.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j.to_dict()
