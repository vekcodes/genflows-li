"""Prompt builders for LinkedIn mining + generation. Each returns (system, prompt).

Kept in one place so the contracts (and the JSON shapes we parse) are easy to audit.
"""
from __future__ import annotations


# ---- Mining (Layer E) ----

def pain_points(comment_lines: str, k: int) -> tuple[str, str]:
    system = (
        "You are an audience-research analyst. You read LinkedIn post comments and surface the "
        "recurring questions, frustrations, and pain-points the audience expresses, in their own framing."
    )
    prompt = (
        f"Comments (one per line, with like counts):\n{comment_lines}\n\n"
        f"Return ONLY a JSON array of up to {k} objects, most common first:\n"
        '[{"question": "the audience pain-point as a clear general question", '
        '"frequency": <int estimate of how many comments express it>, '
        '"example": "<short representative quote>"}]\n'
        "JSON only, no prose."
    )
    return system, prompt


def patterns(hook_lines: str) -> tuple[str, str]:
    system = (
        "You are a LinkedIn content strategist who clusters high-performing posts into "
        "repeatable, namable formats based on their opening hooks."
    )
    prompt = (
        f"High-performing post openings (with engagement multiplier vs author median):\n{hook_lines}\n\n"
        "Cluster them into recurring formats. Return ONLY a JSON array:\n"
        '[{"label": "short format name", "description": "why it works, one sentence", '
        '"example_titles": ["exact hook from the list", ...]}]\n'
        "JSON only."
    )
    return system, prompt


def style_card(author_name: str, excerpt: str) -> tuple[str, str]:
    system = "You extract a concise, reusable style-card describing a LinkedIn creator's writing voice."
    prompt = (
        f'Top posts from "{author_name}":\n"""\n{excerpt}\n"""\n\n'
        'Return ONLY JSON: {"tone": "...", "pacing": "posting cadence and rhythm", '
        '"hooks": ["how they open posts — specific patterns", ...], '
        '"vocabulary": ["signature words/phrases they use", ...]}\n'
        "Keep each field short. JSON only."
    )
    return system, prompt


# ---- Generation (Layer G) ----

def ideas(context: str, n: int, guidance: str = "") -> tuple[str, str]:
    system = (
        "You are a LinkedIn content strategist for B2B founders and executives. "
        "You propose specific, compelling post ideas grounded in proven demand and "
        "written in formats that drive engagement on LinkedIn. You SYNTHESIZE — you "
        "never copy or lightly reword an existing post."
    )
    ask = f'\n\nUSER REQUEST: "{guidance.strip()}"\nHonor this request while staying grounded in the evidence above.' if guidance.strip() else ""
    prompt = (
        f"{context}{ask}\n\n"
        f"Propose {n} distinct, ORIGINAL LinkedIn post ideas. Treat the evidence above as proof of what "
        "the audience wants — NOT as templates. Hard rules:\n"
        "- Do NOT reuse, rephrase, or lightly tweak any single PROVEN HOOK / existing post opening. "
        "Each idea must be clearly different from every post listed above.\n"
        "- Build each idea by COMBINING at least two signals (e.g. a proven format + an audience "
        "pain-point, or two topics) into a fresh angle not yet posted.\n"
        "- Add a genuinely new hook, angle, or specific case/example — not just a synonym swap.\n"
        "- Each of the ideas must also differ from the others.\n"
        "Return ONLY a JSON array:\n"
        '[{"title": "the opening hook line (≤120 chars, punchy)", '
        '"angle": "one-line angle — what makes it unique and why it matters now", '
        '"format": "<one of the formats above, or: listicle | story | howto | contrarian | other>", '
        '"evidence": ["which 2+ proven signals this combines"]}]\n'
        "Hooks must be concrete and original. JSON only."
    )
    return system, prompt


def refine_idea(
    prev_title: str, prev_angle: str, prev_score, drivers_hint: str, context: str, guidance: str
) -> tuple[str, str]:
    system = (
        "You are a LinkedIn strategist improving a post idea to maximise its predicted engagement, "
        "while keeping it honest and grounded in the creators' proven content."
    )
    ask = f' The user asked: "{guidance.strip()}".' if guidance.strip() else ""
    prompt = (
        f"{context}\n\n"
        f'Current idea: "{prev_title}" — {prev_angle}\n'
        f"Predicted engagement: {prev_score}/100 — too low.\n"
        f"On these profiles, posts that perform tend to use: {drivers_hint}.{ask}\n\n"
        "Propose ONE stronger idea that should score higher. Keep it ORIGINAL — it must NOT "
        "duplicate or lightly reword any existing hook above. Return ONLY JSON:\n"
        '{"title": "...", "angle": "one-line angle — what makes it new", "format": "...", '
        '"evidence": ["which proven signals it combines"]}\n'
        "JSON only."
    )
    return system, prompt


def post_outline(title: str, angle: str, style: str) -> tuple[str, str]:
    system = "You are a LinkedIn ghostwriter. You always plan a post structure before writing."
    prompt = (
        f"Post hook: {title}\nAngle: {angle}\n{style}\n\n"
        "Plan the post as ordered sections. Return ONLY a JSON array:\n"
        '[{"beat": "Hook|Body|CTA", "heading": "short label", '
        '"intent": "what this section accomplishes"}]\n'
        "Include exactly 1 Hook (the opening line), 2-3 Body sections (the value), "
        "and 1 CTA (the closing ask). JSON only."
    )
    return system, prompt


def expand_section(title: str, style: str, outline_summary: str, beat: str, heading: str, intent: str) -> tuple[str, str]:
    system = "You are a LinkedIn ghostwriter writing in the creator's authentic voice."
    prompt = (
        f"Post hook: {title}\n{style}\nFull outline:\n{outline_summary}\n\n"
        f"Write the content for THIS section only — {beat}: {heading}.\n"
        f"Goal of the section: {intent}\n"
        "LinkedIn-native style: short paragraphs (1-2 sentences), white space between paragraphs, "
        "conversational and direct. 60-120 words. Plain text only — no markdown headings."
    )
    return system, prompt


def assemble_post(title: str, sections: list[dict], style: str) -> tuple[str, str]:
    """Polish and assemble sections into a final LinkedIn post."""
    body = "\n\n".join(s.get("content", "") for s in sections if s.get("content"))
    system = "You are a LinkedIn ghostwriter polishing a post for maximum engagement."
    prompt = (
        f"{style}\n\n"
        "Tighten the following LinkedIn post for engagement and authentic voice. "
        "Keep the hook strong (first 2 lines are what people see before 'see more'). "
        "Ensure good use of line breaks and white space. End with a clear CTA or question. "
        "Return the complete final post text only (no JSON, no headings, no preamble):\n\n"
        f"Hook: {title}\n\n{body}"
    )
    return system, prompt


def first_comment(title: str, angle: str, post_text: str, niche: str | None, cta: str | None) -> tuple[str, str]:
    system = (
        "You write LinkedIn first comments that drive bookings and conversations for B2B creators. "
        "The first comment goes out immediately after publishing to boost early engagement."
    )
    offer = cta.strip() if cta and cta.strip() else "a free strategy call (use [BOOKING LINK] as the placeholder)"
    prompt = (
        f"Post hook: {title}\n"
        f"Angle: {angle}\n"
        f"Audience: {niche or 'infer from the post'}\n"
        f"Post text:\n\"\"\"\n{post_text[:1500]}\n\"\"\"\n\n"
        f"Offer / CTA: {offer}\n\n"
        "Write the first comment (posted by the creator right after publishing):\n"
        "- 2-3 sentences expanding one specific point from the post\n"
        "- One clear call-to-action using the offer above (use [BOOKING LINK] if no link given)\n"
        "- Conversational, not salesy\n"
        "Return ONLY the comment text — no preamble, no JSON."
    )
    return system, prompt


def image_prompt(title: str, angle: str, post_text: str) -> tuple[str, str]:
    """A ready-to-use image-generation prompt for a LinkedIn post image (GenFlows-branded)."""
    system = (
        "You are a LinkedIn visual content director for GenFlows, a B2B GTM-engineering agency. "
        "You write a single, vivid image-generation prompt (for Midjourney/DALL·E) "
        "that makes a high-CTR LinkedIn post image AND follows the GenFlows brand system exactly."
    )
    prompt = (
        f"Post hook: {title}\n"
        f"Angle: {angle}\n"
        f"Post excerpt:\n\"\"\"\n{post_text[:800]}\n\"\"\"\n\n"
        "GENFLOWS BRAND SYSTEM (non-negotiable):\n"
        "- Background: deep navy #0A1F35, flat or subtle gradient.\n"
        "- ONE accent color only: orange #E67E22 for the focal element.\n"
        "- Text overlay: 2-4 words MAX in heavy geometric sans-serif, white #FFFFFF, "
        "with exactly ONE word in orange #E67E22.\n"
        "- Aesthetic: clean, premium, engineering/GTM look — pipelines, dashboards, "
        "flow diagrams as glowing line-art; generous negative space.\n"
        "- LinkedIn 1:1 square (1200x1200) or 1.91:1 landscape (1200x628).\n\n"
        "Write ONE image-generation prompt obeying ALL rules above. "
        "Specify: subject, the exact overlay text, which word is orange, colors by hex. "
        "Return ONLY the prompt text — no preamble, no quotes."
    )
    return system, prompt


def polish(text: str) -> tuple[str, str]:
    system = "You are a sharp LinkedIn editor improving a post for engagement and authenticity."
    prompt = (
        "Tighten the following LinkedIn post for engagement and flow WITHOUT changing its structure "
        "or meaning. Ensure white space between short paragraphs. Keep the hook on its own line. "
        f"Return the full improved post text only:\n\n{text}"
    )
    return system, prompt
