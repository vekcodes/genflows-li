"""One-shot orchestration: LinkedIn profiles + a request → the whole pipeline → posts.

Behaves like a researcher, not a batch job:
  1. Scrape posts from each LinkedIn profile/company (metadata + comments).
  2. Analyze engagement performance + what's trending now.
  3. Mine winning formats, audience pain-points, style.
  4. For each post, ONE AT A TIME: research an idea → check engagement → if weak, re-research →
     repeat until strong → then write the full LinkedIn post. Deliberate, not rushed.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field

from sqlmodel import Session, select

from . import brain, insights
from .db import engine
from .generation import refine
from .generation import script as script_gen
from .ingestion.pipeline import ingest_source
from .llm.base import LLMError
from .llm.factory import get_llm
from .models import LinkedInPost, Source

log = logging.getLogger("brain.assistant")


@dataclass
class Step:
    key: str
    label: str
    status: str = "pending"
    detail: str = ""


@dataclass
class Job:
    id: str
    prompt: str
    status: str = "running"
    steps: list[Step] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "prompt": self.prompt, "status": self.status,
            "steps": [asdict(s) for s in self.steps], "result": self.result, "error": self.error,
        }


_JOBS: dict[str, Job] = {}

FIXED_STEPS = [
    ("scrape", "Scraping all posts (text + comments)"),
    ("analyze", "Analyzing engagement & what's trending now"),
    ("mine", "Mining winning formats, pain-points & style"),
]


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def start(*, channels, prompt, niche=None, n_scripts=3, target_score=60.0, offer=None) -> Job:
    steps = [Step(k, l) for k, l in FIXED_STEPS]
    for i in range(n_scripts):
        steps.append(Step(f"script-{i + 1}", f"Post {i + 1}: research → engagement score → hook · body · CTA"))
    job = Job(id=uuid.uuid4().hex[:12], prompt=prompt, steps=steps)
    _JOBS[job.id] = job
    threading.Thread(
        target=_run,
        kwargs=dict(job=job, channels=channels, prompt=prompt, niche=niche,
                    n_scripts=n_scripts, target_score=target_score, offer=offer),
        daemon=True,
    ).start()
    return job


def _step(job: Job, key: str) -> Step:
    return next(s for s in job.steps if s.key == key)


def _run(*, job, channels, prompt, niche, n_scripts, target_score, offer=None) -> None:
    try:
        with Session(engine) as session:
            # 1) Scrape posts from all sources.
            s = _step(job, "scrape"); s.status = "running"
            total_new = 0
            author_ids: list[str] = []
            for i, url in enumerate(channels):
                s.detail = f"profile {i + 1}/{len(channels)}… ({total_new} new so far)"
                src = session.exec(select(Source).where(Source.url == url)).first()
                if not src:
                    src = Source(url=url, kind=_guess_kind(url), niche=niche)
                    session.add(src); session.commit(); session.refresh(src)
                run = ingest_source(session, src, max_new=None)
                total_new += run.new_videos
                if src.external_id:
                    author_ids.append(src.external_id)
            n_posts = len(session.exec(select(LinkedInPost)).all())
            s.status = "done"; s.detail = f"{total_new} new · {n_posts} posts in brain"

            # 2) Analyze + trending
            s = _step(job, "analyze"); s.status = "running"
            outliers = brain.outliers(session, min_multiplier=1.0, limit=10)
            trend = brain.trending(session, limit=8)
            top_outliers = [{"title": o.title, "multiplier": o.multiplier} for o in outliers[:5]]
            s.status = "done"; s.detail = f"{len(outliers)} top posts · {len(trend)} trending"

            llm_ready = bool(get_llm() and get_llm().available())
            primary_author = author_ids[0] if author_ids else None

            # 3) Mine insights
            s = _step(job, "mine"); s.status = "running"
            if not llm_ready:
                s.status = "skipped"; s.detail = "Claude not available"
            else:
                try:
                    pats = insights.mine_patterns(session, niche=niche, min_multiplier=2.0)
                    pains = insights.mine_pain_points(session, niche=niche)
                    for aid in author_ids[:3]:
                        try:
                            insights.mine_style_card(session, channel_id=aid)
                        except Exception:
                            pass
                    s.status = "done"; s.detail = f"{len(pats)} formats · {len(pains)} pain-points"
                except LLMError as exc:
                    s.status = "skipped"; s.detail = str(exc)

            # 4) Craft posts ONE AT A TIME (research ↔ engagement loop, then write)
            scripts = []
            if not llm_ready:
                for i in range(n_scripts):
                    st = _step(job, f"script-{i + 1}"); st.status = "skipped"; st.detail = "Claude not available"
                _finish(job, scripts, total_new, n_posts, top_outliers, False,
                        "Claude isn't available on the server, so posts were skipped.")
                return

            for i in range(n_scripts):
                st = _step(job, f"script-{i + 1}"); st.status = "running"
                def progress(msg, _st=st):
                    _st.detail = msg
                idea = refine.craft(
                    session, llm=get_llm(), channel_id=primary_author, niche=niche,
                    guidance=prompt, target_score=target_score, on_progress=progress,
                )
                progress(f"score {idea.get('virality_score')} — writing post…")
                doc = script_gen.generate_script(
                    session, title=idea["title"], angle=idea.get("angle", ""), channel_id=primary_author,
                )
                progress(f"score {idea.get('virality_score')} — writing first comment & CTA…")
                desc = script_gen.generate_description(
                    session, title=idea["title"], angle=idea.get("angle", ""),
                    script_markdown=doc["markdown"], niche=niche, cta=offer, llm=get_llm(),
                )
                scripts.append({
                    **idea, "markdown": doc["markdown"], "sections": doc["sections"], "description": desc,
                })
                st.status = "done"
                st.detail = f'"{idea["title"][:48]}" · score {idea.get("virality_score")}'

            _finish(job, scripts, total_new, n_posts, top_outliers, True,
                    "Each idea was researched and refined until it cleared the engagement bar, then written as a LinkedIn post.")
    except Exception as exc:
        log.exception("assistant job %s failed", job.id)
        for st in job.steps:
            if st.status == "running":
                st.status = "error"; st.detail = str(exc)
        job.status = "error"; job.error = str(exc)


def _finish(job, scripts, new_videos, videos, top_outliers, llm, note) -> None:
    job.result = {
        "scripts": scripts,
        "summary": {"new_videos": new_videos, "videos": videos, "outliers": top_outliers,
                    "llm": llm, "note": note},
    }
    job.status = "done"


def _guess_kind(url: str):
    from .models import SourceKind
    if "/company/" in url or "/showcase/" in url:
        return SourceKind.company
    if "/hashtag/" in url:
        return SourceKind.hashtag
    return SourceKind.profile
