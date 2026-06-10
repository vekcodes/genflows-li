"""Outline → section-wise expand → polish (one LLM call per beat, beats run concurrently)."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlmodel import Session

from .. import insights
from ..llm.base import LLMProvider
from ..llm.factory import require_llm
from ..llm.parse import complete_json
from .ideas import _resolve_store
from . import prompts

VALID_BEATS = {"Hook", "Setup", "Body", "CTA"}


def _style_line(session: Session, channel_id: str | None, *, store=None) -> str:
    if not channel_id:
        return ""

    # Prefer the wiki's channel page when enabled+populated; fall back to the DB style card.
    store = _resolve_store(store)
    if store is not None:
        from ..wiki import read as wiki_read

        style = wiki_read.channel_style(store, channel_id=channel_id)
        if style:
            return (
                f"Style — tone: {style.get('tone', '')}; pacing: {style.get('pacing', '')}; "
                f"hooks: {', '.join(style.get('hooks', [])[:4])}; "
                f"vocabulary: {', '.join(style.get('vocabulary', [])[:6])}"
            )

    card = insights.get_style_card(session, channel_id)
    if not card:
        return ""
    return (
        f"Style — tone: {card.tone}; pacing: {card.pacing}; "
        f"hooks: {', '.join(card.hooks[:4])}; vocabulary: {', '.join(card.vocabulary[:6])}"
    )


def generate_script(
    session: Session,
    *,
    title: str,
    angle: str = "",
    channel_id: str | None = None,
    polish: bool = True,
    llm: LLMProvider | None = None,
    on_progress: Callable[[str], None] = lambda _msg: None,
) -> dict:
    llm = llm or require_llm()
    style = _style_line(session, channel_id)

    # 1) Outline
    on_progress("script: outlining")
    sys_o, p_o = prompts.outline(title, angle, style)
    raw = complete_json(llm, p_o, system=sys_o)
    sections = [
        {
            "beat": (s.get("beat") if s.get("beat") in VALID_BEATS else "Body"),
            "heading": str(s.get("heading", "")).strip(),
            "intent": str(s.get("intent", "")).strip(),
        }
        for s in raw
        if isinstance(s, dict)
    ]
    if not sections:
        raise ValueError("LLM returned no usable outline")

    outline_summary = "\n".join(f"{i+1}. {s['beat']} — {s['heading']}" for i, s in enumerate(sections))

    # 2) Expand the beats concurrently (independent LLM calls; order restored by section dict).
    # Progress/DB side effects stay on this thread — workers only call the LLM.
    total = len(sections)
    on_progress(f"script: writing {total} beats")

    def _expand_one(s: dict) -> str:
        sys_e, p_e = prompts.expand(title, style, outline_summary, s["beat"], s["heading"], s["intent"])
        return llm.complete(p_e, system=sys_e).strip()

    with ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        futures = {pool.submit(_expand_one, s): s for s in sections}
        for done, future in enumerate(as_completed(futures), start=1):
            futures[future]["content"] = future.result()  # propagates the first failure
            on_progress(f"script: writing beats {done}/{total}")

    # 3) Assemble markdown
    body = "\n\n".join(f"## {s['beat']} — {s['heading']}\n\n{s['content']}" for s in sections)
    markdown = f"# {title}\n\n{body}\n"

    # 4) Polish (optional)
    if polish:
        on_progress("script: polishing")
        sys_p, p_p = prompts.polish(markdown)
        polished = llm.complete(p_p, system=sys_p).strip()
        if polished:
            markdown = polished

    return {"title": title, "sections": sections, "markdown": markdown}


def generate_description(
    session: Session,
    *,
    title: str,
    angle: str = "",
    script_markdown: str = "",
    niche: str | None = None,
    cta: str | None = None,
    llm: LLMProvider | None = None,
) -> str:
    """A YouTube description: SEO-optimized opener + book-a-meeting CTA + hashtags."""
    llm = llm or require_llm()
    sys_d, p_d = prompts.description(title, angle, script_markdown, niche, cta)
    return llm.complete(p_d, system=sys_d).strip()
