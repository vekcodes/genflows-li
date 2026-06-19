"""The human-brain loop: research an idea → check engagement score → if weak, re-research → repeat
until it's strong enough, then hand off to post writing.

Deliberate, not rushed — one idea is crafted to an engagement target before any post is written.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlmodel import Session

from .. import virality
from ..config import get_settings
from ..llm.base import LLMProvider
from ..llm.parse import complete_json
from . import ideas as ideas_gen
from . import novelty, prompts

# Map virality-model features to human-readable "what works" hints.
_DRIVER_PHRASES = {
    "is_listicle": "a numbered listicle format",
    "has_number": "a specific number in the hook",
    "is_contrarian": "a contrarian / unpopular-opinion angle",
    "is_question": "a curiosity-gap question",
    "has_emoji": "strategic emoji use",
    "has_cta": "a strong closing call-to-action",
    "is_story": "a personal story framing",
    "is_how_to": "a concrete how-to or framework",
    "has_hook": "a punchy standalone opening line",
    "line_count": "more paragraph breaks and white space",
}


def driver_hints(session: Session) -> str:
    report = virality.backtest(session)
    feats = report.get("top_features") or []
    pos = [f["feature"] for f in feats if f.get("weight", 0) > 0]
    phrases = [_DRIVER_PHRASES.get(f, f) for f in pos][:4]
    if not phrases:
        return "a clear number or outcome, a curiosity gap, or a contrarian angle"
    return ", ".join(phrases)


def craft(
    session: Session,
    *,
    llm: LLMProvider,
    channel_id: str | None,
    niche: str | None,
    guidance: str,
    target_score: float = 60.0,
    max_iters: int = 4,
    duration_sec: int = 600,
    on_progress: Callable[[str], None] = lambda _: None,
) -> dict:
    """Loop research→virality until score ≥ target (or max_iters). Returns the best idea dict."""
    hints = driver_hints(session)

    on_progress("researching ideas…")
    res = ideas_gen.generate_ideas(
        session, channel_id=channel_id, niche=niche, n=4, min_score=0.0,
        guidance=guidance, query=guidance or (niche or ""), duration_sec=duration_sec, llm=llm,
    )
    candidates = res["ideas"]
    best = candidates[0] if candidates else None
    trained = res.get("model_trained")

    # If the model can't score yet, don't loop — proceed with the top idea.
    if not best or not trained or best.get("virality_score") is None:
        on_progress("virality model not trained — proceeding with best idea")
        return best or {"title": guidance or "Untitled", "angle": "", "format": "other",
                        "evidence": [], "virality_score": None, "predicted_viral": None,
                        "nearest_analogs": []}

    context = ideas_gen._build_context(session, channel_id=channel_id, niche=niche, query=guidance)
    existing = novelty.existing_titles(session, channel_id)
    nov_threshold = get_settings().novelty_max_similarity

    for it in range(1, max_iters + 1):
        score = best.get("virality_score") or 0
        on_progress(f"virality {score} (try {it}/{max_iters})")
        if score >= target_score:
            on_progress(f"virality {score} ✓ — strong enough")
            return best

        # Re-research a stronger angle, informed by the model's drivers.
        sys_p, p = prompts.refine_idea(best["title"], best.get("angle", ""), score, hints, context, guidance)
        try:
            data = complete_json(llm, p, system=sys_p)
        except Exception:
            break
        cand = data[0] if isinstance(data, list) and data else data
        if not isinstance(cand, dict) or not str(cand.get("title", "")).strip():
            break
        title = str(cand["title"]).strip()
        sim = novelty.max_similarity(title, existing)
        if sim > nov_threshold:  # a higher score isn't worth it if it's a near-copy
            on_progress(f"skipped a near-duplicate refinement (sim {round(sim, 2)})")
            continue
        v = virality.score(session, title=title)
        scored = {
            "title": title,
            "angle": str(cand.get("angle", "")).strip(),
            "format": str(cand.get("format", "other")).strip(),
            "evidence": [str(e).strip() for e in (cand.get("evidence") or [])],
            "virality_score": v.get("virality_score"),
            "predicted_viral": v.get("predicted_viral"),
            "nearest_analogs": v.get("nearest_analogs", []),
            "novelty": round(1 - sim, 3),
        }
        if (scored["virality_score"] or 0) > (best["virality_score"] or 0):
            best = scored

    on_progress(f"virality {best.get('virality_score')} (best of {max_iters})")
    return best
