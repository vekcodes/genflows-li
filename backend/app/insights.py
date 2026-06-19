"""Layer E LLM mining — LinkedIn edition.

Mines: comment pain-points · post format patterns · author style cards.
Each writes reusable Brain state (DB tables) and takes an injectable `llm`
so it can be unit-tested with a fake provider.
"""
from __future__ import annotations

from sqlmodel import Session, delete, select

from . import brain
from .llm.base import LLMProvider
from .llm.factory import require_llm
from .llm.parse import complete_json
from .generation import prompts
from .models import FormatPattern, LinkedInPost, PainPoint, PostComment, StyleCard, Source

MAX_COMMENTS = 200
MAX_POSTS = 40
MAX_POST_CHARS = 8000


def _post_ids_for_niche(session: Session, niche: str | None) -> set[str] | None:
    if not niche:
        return None
    sids = session.exec(select(Source.id).where(Source.niche == niche)).all()
    if not sids:
        return set()
    return set(session.exec(select(LinkedInPost.id).where(LinkedInPost.source_id.in_(sids))).all())


def mine_pain_points(
    session: Session, *, niche: str | None = None, k: int = 12, llm: LLMProvider | None = None
) -> list[PainPoint]:
    llm = llm or require_llm()
    pid_filter = _post_ids_for_niche(session, niche)

    q = select(PostComment).order_by(PostComment.likes.desc()).limit(MAX_COMMENTS)
    comments = [c for c in session.exec(q).all() if pid_filter is None or c.post_id in pid_filter]
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
    session: Session, *, niche: str | None = None, min_multiplier: float = 2.0,
    llm: LLMProvider | None = None,
) -> list[FormatPattern]:
    llm = llm or require_llm()
    high_engagement = brain.outliers(session, min_multiplier=min_multiplier, limit=MAX_POSTS)
    if not high_engagement:
        return []

    by_text = {o.title.strip().lower(): o for o in high_engagement}
    lines = "\n".join(f"{o.multiplier}x  —  {o.title.strip()}" for o in high_engagement)
    system, prompt = prompts.patterns(lines)
    data = complete_json(llm, prompt, system=system)

    session.exec(delete(FormatPattern).where(FormatPattern.niche == niche))
    rows: list[FormatPattern] = []
    for item in data:
        examples = [str(t).strip() for t in (item.get("example_titles") or [])]
        matched = [by_text[t.lower()] for t in examples if t.lower() in by_text]
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
    """Extract a style card from a LinkedIn author's top posts."""
    llm = llm or require_llm()
    posts = session.exec(
        select(LinkedInPost)
        .where(LinkedInPost.author_id == channel_id)
        .order_by(LinkedInPost.reactions.desc())
        .limit(10)
    ).all()
    if not posts:
        return None

    author_name = next((p.author_name for p in posts if p.author_name), channel_id)
    excerpt = "\n---\n".join(p.text for p in posts)[:MAX_POST_CHARS]
    system, prompt = prompts.style_card(author_name, excerpt)
    data = complete_json(llm, prompt, system=system)

    existing = session.get(StyleCard, channel_id)
    card = existing or StyleCard(channel_id=channel_id)
    card.channel_name = author_name
    card.tone = str(data.get("tone", "")).strip()
    card.pacing = str(data.get("pacing", "")).strip()
    card.hooks = [str(h).strip() for h in (data.get("hooks") or [])]
    card.vocabulary = [str(v).strip() for v in (data.get("vocabulary") or [])]
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


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
