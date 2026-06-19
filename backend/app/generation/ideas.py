"""Evidence-ranked LinkedIn post idea generation, gated by the engagement model."""
from __future__ import annotations

from sqlmodel import Session

from .. import brain, insights, virality
from ..config import get_settings
from ..llm.base import LLMProvider
from ..llm.factory import require_llm
from ..llm.parse import complete_json
from . import novelty, prompts


def _resolve_store(store):
    if not get_settings().brain_wiki_enabled:
        return None
    if store is not None:
        return store
    try:
        from .. import wiki
        return wiki.default_store()
    except Exception:
        return None


def _build_context(
    session: Session,
    *,
    channel_id: str | None,
    niche: str | None,
    query: str | None = None,
    store=None,
) -> str:
    parts: list[str] = []
    store = _resolve_store(store)
    wiki_read = None
    if store is not None:
        from ..wiki import read as wiki_read

    # Trending posts (velocity-ranked).
    trend = brain.trending(session, limit=8)
    if trend:
        parts.append("TRENDING NOW (recent posts by velocity):\n" + "\n".join(
            f"- {t.velocity}/day · {t.multiplier}x  {t.title}" for t in trend
        ))

    # Creator style.
    style = wiki_read.channel_style(store, channel_id=channel_id) if wiki_read else None
    if style:
        parts.append(
            f"CREATOR STYLE — tone: {style.get('tone', '')}; pacing: {style.get('pacing', '')}; "
            f"hooks: {', '.join(style.get('hooks', [])[:5])}; "
            f"vocabulary: {', '.join(style.get('vocabulary', [])[:8])}"
        )
    elif channel_id:
        card = insights.get_style_card(session, channel_id)
        if card:
            parts.append(
                f"CREATOR STYLE — tone: {card.tone}; pacing: {card.pacing}; "
                f"hooks: {', '.join(card.hooks[:5])}; vocabulary: {', '.join(card.vocabulary[:8])}"
            )

    # Proven formats.
    wiki_formats = wiki_read.formats(store, limit=6) if wiki_read else []
    if wiki_formats:
        parts.append("PROVEN FORMATS:\n" + "\n".join(
            f"- {f['label']} ({f['avg_multiplier']}x): {f['summary']}" for f in wiki_formats
        ))
    else:
        pats = insights.list_patterns(session, niche)[:6]
        if pats:
            parts.append("PROVEN FORMATS:\n" + "\n".join(
                f"- {p.label} ({p.avg_multiplier}x): {p.description}" for p in pats
            ))

    # Audience pain-points.
    wiki_pains = wiki_read.pains(store, limit=8) if wiki_read else []
    if wiki_pains:
        parts.append("AUDIENCE PAIN-POINTS:\n" + "\n".join(
            f"- ({p['source_count']}) {p['question']}" for p in wiki_pains
        ))
    else:
        pains = insights.list_pain_points(session, niche)[:8]
        if pains:
            parts.append("AUDIENCE PAIN-POINTS:\n" + "\n".join(
                f"- ({p.frequency}) {p.question}" for p in pains
            ))

    # Proven topics — from high-engagement post hooks.
    proven = brain.outliers(session, min_multiplier=2.0, limit=12)
    if proven:
        parts.append("PROVEN HOOKS (posts that beat author median):\n" + "\n".join(
            f"- {o.multiplier}x  {o.title}" for o in proven
        ))

    return "\n\n".join(parts) if parts else "No insights yet — propose ideas for this niche."


def generate_ideas(
    session: Session,
    *,
    channel_id: str | None = None,
    niche: str | None = None,
    n: int = 8,
    duration_sec: int = 0,      # not used for LinkedIn but kept for API compat
    min_score: float = 0.0,
    top: int | None = None,
    viral_threshold: float = 2.0,
    guidance: str = "",
    query: str | None = None,
    llm: LLMProvider | None = None,
) -> dict:
    """Generate LinkedIn post ideas, scored + gated by the engagement model."""
    llm = llm or require_llm()
    context = _build_context(session, channel_id=channel_id, niche=niche, query=query or guidance)
    system, prompt = prompts.ideas(context, n, guidance)
    raw = complete_json(llm, prompt, system=system)

    existing = novelty.existing_titles(session, channel_id)
    scored: list[dict] = []
    for item in raw:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        v = virality.score(session, title=title, threshold=viral_threshold)
        sim = novelty.max_similarity(title, existing)
        scored.append({
            "title": title,
            "angle": str(item.get("angle", "")).strip(),
            "format": str(item.get("format", "other")).strip(),
            "evidence": [str(e).strip() for e in (item.get("evidence") or [])],
            "virality_score": v.get("virality_score"),
            "predicted_viral": v.get("predicted_viral"),
            "nearest_analogs": v.get("nearest_analogs", []),
            "model_status": v.get("status"),
            "novelty": round(1 - sim, 3),
            "_similarity": sim,
        })

    threshold = get_settings().novelty_max_similarity
    unique = [s for s in scored if s["_similarity"] <= threshold]
    if not unique and scored:
        unique = [min(scored, key=lambda s: s["_similarity"])]
    scored = unique
    for s in scored:
        s.pop("_similarity", None)

    trained = any(s["model_status"] == "ok" for s in scored)
    if trained:
        scored = [s for s in scored if (s["virality_score"] or 0) >= min_score]
        scored.sort(key=lambda s: s["virality_score"] or 0, reverse=True)
    if top:
        scored = scored[:top]

    return {
        "model_trained": trained,
        "viral_threshold": viral_threshold,
        "min_score": min_score,
        "count": len(scored),
        "ideas": scored,
    }
