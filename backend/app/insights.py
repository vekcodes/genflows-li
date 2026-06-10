"""Layer E LLM mining: comment pain-points · title/format patterns · style-cards.

Each writes reusable Brain state (DB tables) and takes an injectable `llm` so it can be
unit-tested with a fake provider. Real runs use Claude via the configured provider.
"""
from __future__ import annotations

from sqlmodel import Session, delete, select

from . import brain
from .llm.base import LLMProvider
from .llm.factory import require_llm
from .llm.parse import complete_json
from .generation import prompts
from .models import Comment, FormatPattern, PainPoint, StyleCard, Transcript, Video

MAX_COMMENTS = 200
MAX_TITLES = 40
MAX_TRANSCRIPT_CHARS = 6000


def _video_ids_for_niche(session: Session, niche: str | None) -> set[str] | None:
    if not niche:
        return None
    from .models import Source

    sids = session.exec(select(Source.id).where(Source.niche == niche)).all()
    if not sids:
        return set()
    return set(session.exec(select(Video.id).where(Video.source_id.in_(sids))).all())


# ---- Mining ----

def mine_pain_points(
    session: Session, *, niche: str | None = None, k: int = 12, llm: LLMProvider | None = None
) -> list[PainPoint]:
    llm = llm or require_llm()
    vid_filter = _video_ids_for_niche(session, niche)

    q = select(Comment).order_by(Comment.likes.desc()).limit(MAX_COMMENTS)
    comments = [c for c in session.exec(q).all() if vid_filter is None or c.video_id in vid_filter]
    if not comments:
        return []

    lines = "\n".join(f"({c.likes}👍) {c.text.strip()[:300]}" for c in comments if c.text.strip())
    system, prompt = prompts.pain_points(lines, k)
    data = complete_json(llm, prompt, system=system)

    session.exec(delete(PainPoint).where(PainPoint.niche == niche))
    rows = [
        PainPoint(
            niche=niche,
            question=str(item.get("question", "")).strip(),
            frequency=int(item.get("frequency", 0) or 0),
            example=(str(item.get("example", "")).strip() or None),
        )
        for item in data
        if str(item.get("question", "")).strip()
    ]
    session.add_all(rows)
    session.commit()
    return rows


def mine_patterns(
    session: Session, *, niche: str | None = None, min_multiplier: float = 3.0,
    llm: LLMProvider | None = None,
) -> list[FormatPattern]:
    llm = llm or require_llm()
    outliers = brain.outliers(session, min_multiplier=min_multiplier, limit=MAX_TITLES)
    if not outliers:
        return []

    by_title = {o.title.strip().lower(): o for o in outliers}
    lines = "\n".join(f"{o.multiplier}x  —  {o.title.strip()}" for o in outliers)
    system, prompt = prompts.patterns(lines)
    data = complete_json(llm, prompt, system=system)

    session.exec(delete(FormatPattern).where(FormatPattern.niche == niche))
    rows: list[FormatPattern] = []
    for item in data:
        examples = [str(t).strip() for t in (item.get("example_titles") or [])]
        matched = [by_title[t.lower()] for t in examples if t.lower() in by_title]
        avg = round(sum(o.multiplier for o in matched) / len(matched), 2) if matched else 0.0
        rows.append(
            FormatPattern(
                niche=niche,
                label=str(item.get("label", "")).strip(),
                description=str(item.get("description", "")).strip(),
                avg_multiplier=avg,
                example_video_ids=[o.video_id for o in matched],
            )
        )
    rows = [r for r in rows if r.label]
    session.add_all(rows)
    session.commit()
    return rows


def mine_style_card(
    session: Session, *, channel_id: str, llm: LLMProvider | None = None
) -> StyleCard | None:
    llm = llm or require_llm()
    rows = session.exec(
        select(Transcript.text, Video.channel_name)
        .join(Video, Video.id == Transcript.video_id)
        .where(Video.channel_id == channel_id)
        .limit(8)
    ).all()
    if not rows:
        return None

    channel_name = next((r[1] for r in rows if r[1]), channel_id)
    excerpt = "\n---\n".join(t for t, _ in rows)[:MAX_TRANSCRIPT_CHARS]
    system, prompt = prompts.style_card(channel_name, excerpt)
    data = complete_json(llm, prompt, system=system)

    existing = session.get(StyleCard, channel_id)
    card = existing or StyleCard(channel_id=channel_id)
    card.channel_name = channel_name
    card.tone = str(data.get("tone", "")).strip()
    card.pacing = str(data.get("pacing", "")).strip()
    card.hooks = [str(h).strip() for h in (data.get("hooks") or [])]
    card.vocabulary = [str(v).strip() for v in (data.get("vocabulary") or [])]
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


# ---- Read helpers (used by generation + the API) ----

def list_pain_points(session: Session, niche: str | None = None) -> list[PainPoint]:
    q = select(PainPoint).order_by(PainPoint.frequency.desc())
    if niche:
        q = q.where(PainPoint.niche == niche)
    return list(session.exec(q).all())


def list_patterns(session: Session, niche: str | None = None) -> list[FormatPattern]:
    q = select(FormatPattern).order_by(FormatPattern.avg_multiplier.desc())
    if niche:
        q = q.where(FormatPattern.niche == niche)
    return list(session.exec(q).all())


def list_style_cards(session: Session) -> list[StyleCard]:
    return list(session.exec(select(StyleCard)).all())


def get_style_card(session: Session, channel_id: str) -> StyleCard | None:
    return session.get(StyleCard, channel_id)
