"""One-shot orchestration: channels + a request → the whole pipeline → scripts.

Behaves like a researcher, not a batch job:
  1. Dump EVERY video from each channel (full metadata + transcript + comments — no skipping).
  2. Analyze performance + what's trending now (title/transcript velocity).
  3. Mine winning formats, audience pain-points, style.
  4. For each script, ONE AT A TIME: research an idea → check virality → if weak, re-research →
     repeat until strong → then write the full script. Deliberate, not rushed.
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
from .models import Source, Video

log = logging.getLogger("brain.assistant")


@dataclass
class Step:
    key: str
    label: str
    status: str = "pending"  # pending | running | done | skipped | error
    detail: str = ""


@dataclass
class Job:
    id: str
    prompt: str
    status: str = "running"  # running | done | error
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
    ("scrape", "Scraping every video (metadata + transcript + comments)"),
    ("analyze", "Analyzing performance & what's trending now"),
    ("mine", "Mining winning formats, pain-points & style"),
]


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def start(*, channels, prompt, niche=None, n_scripts=3, target_score=60.0, offer=None) -> Job:
    steps = [Step(k, l) for k, l in FIXED_STEPS]
    for i in range(n_scripts):
        steps.append(Step(f"script-{i + 1}", f"Script {i + 1}: research → virality → title · description · script"))
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
            # 1) Scrape EVERYTHING — no caps, no skipping.
            s = _step(job, "scrape"); s.status = "running"
            total_new = 0
            channel_ids: list[str] = []
            for i, url in enumerate(channels):
                s.detail = f"channel {i + 1}/{len(channels)}… ({total_new} new so far)"
                src = session.exec(select(Source).where(Source.url == url)).first()
                if not src:
                    src = Source(url=url, kind=_guess_kind(url), niche=niche)
                    session.add(src); session.commit(); session.refresh(src)
                run = ingest_source(session, src, max_new=None, cap=False)  # ALL videos
                total_new += run.new_videos
                if src.external_id:
                    channel_ids.append(src.external_id)
            n_videos = len(session.exec(select(Video)).all())
            s.status = "done"; s.detail = f"{total_new} new · {n_videos} videos in brain"

            # 2) Analyze + trending
            s = _step(job, "analyze"); s.status = "running"
            outliers = brain.outliers(session, min_multiplier=1.0, limit=10)
            trend = brain.trending(session, limit=8)
            top_outliers = [{"title": o.title, "multiplier": o.multiplier} for o in outliers[:5]]
            s.status = "done"; s.detail = f"{len(outliers)} outliers · {len(trend)} trending"

            llm_ready = bool(get_llm() and get_llm().available())
            primary_channel = channel_ids[0] if channel_ids else None

            # 3) Mine insights
            s = _step(job, "mine"); s.status = "running"
            if not llm_ready:
                s.status = "skipped"; s.detail = "Claude not available"
            else:
                try:
                    pats = insights.mine_patterns(session, niche=niche, min_multiplier=2.0)
                    pains = insights.mine_pain_points(session, niche=niche)
                    for cid in channel_ids[:3]:
                        try:
                            insights.mine_style_card(session, channel_id=cid)
                        except Exception:
                            pass
                    s.status = "done"; s.detail = f"{len(pats)} formats · {len(pains)} pain-points"
                except LLMError as exc:
                    s.status = "skipped"; s.detail = str(exc)

            # 4) Craft scripts ONE AT A TIME (research ↔ virality loop, then write)
            scripts = []
            if not llm_ready:
                for i in range(n_scripts):
                    st = _step(job, f"script-{i + 1}"); st.status = "skipped"; st.detail = "Claude not available"
                _finish(job, scripts, total_new, n_videos, top_outliers, False,
                        "Claude isn't available on the server, so scripts were skipped.")
                return

            for i in range(n_scripts):
                st = _step(job, f"script-{i + 1}"); st.status = "running"
                def progress(msg, _st=st):
                    _st.detail = msg
                idea = refine.craft(
                    session, llm=get_llm(), channel_id=primary_channel, niche=niche,
                    guidance=prompt, target_score=target_score, on_progress=progress,
                )
                progress(f"virality {idea.get('virality_score')} — writing script…")
                doc = script_gen.generate_script(
                    session, title=idea["title"], angle=idea.get("angle", ""), channel_id=primary_channel,
                )
                progress(f"virality {idea.get('virality_score')} — writing description & CTA…")
                desc = script_gen.generate_description(
                    session, title=idea["title"], angle=idea.get("angle", ""),
                    script_markdown=doc["markdown"], niche=niche, cta=offer, llm=get_llm(),
                )
                scripts.append({
                    **idea, "markdown": doc["markdown"], "sections": doc["sections"], "description": desc,
                })
                st.status = "done"
                st.detail = f"“{idea['title'][:48]}” · virality {idea.get('virality_score')}"

            _finish(job, scripts, total_new, n_videos, top_outliers, True,
                    "Each idea was researched and refined until it cleared the virality bar, then written.")
    except Exception as exc:  # noqa: BLE001
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

    if "list=" in url:
        return SourceKind.playlist
    if "watch?v=" in url or "youtu.be/" in url or "/shorts/" in url:
        return SourceKind.video
    return SourceKind.channel
