"""LinkedIn post generation: hook → outline → expand sections → polish.

Replaces the YouTube script writer with LinkedIn-native post generation.
The shape is the same (sections list + markdown) so the rest of the pipeline
(agent, content API) works unchanged.
"""
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

VALID_BEATS = {"Hook", "Body", "CTA"}


def _style_line(session: Session, channel_id: str | None, *, store=None) -> str:
    if not channel_id:
        return ""

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
    """Generate a LinkedIn post: hook → outline sections → expand each → polish."""
    llm = llm or require_llm()
    style = _style_line(session, channel_id)

    # 1) Outline
    on_progress("post: outlining")
    sys_o, p_o = prompts.post_outline(title, angle, style)
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

    # 2) Expand sections concurrently.
    total = len(sections)
    on_progress(f"post: writing {total} sections")

    def _expand_one(s: dict) -> str:
        sys_e, p_e = prompts.expand_section(
            title, style, outline_summary, s["beat"], s["heading"], s["intent"]
        )
        return llm.complete(p_e, system=sys_e).strip()

    with ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        futures = {pool.submit(_expand_one, s): s for s in sections}
        for done, future in enumerate(as_completed(futures), start=1):
            futures[future]["content"] = future.result()
            on_progress(f"post: writing sections {done}/{total}")

    # 3) Assemble and polish the full post.
    on_progress("post: assembling")
    sys_a, p_a = prompts.assemble_post(title, sections, style)
    post_text = llm.complete(p_a, system=sys_a).strip()

    if not post_text:
        post_text = "\n\n".join(s.get("content", "") for s in sections)

    return {"title": title, "sections": sections, "markdown": post_text}


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
    """Generate the first-comment CTA text for a LinkedIn post."""
    llm = llm or require_llm()
    sys_d, p_d = prompts.first_comment(title, angle, script_markdown, niche, cta)
    return llm.complete(p_d, system=sys_d).strip()
