"""Prompt builders for mining + generation. Each returns (system, prompt).

Kept in one place so the contracts (and the JSON shapes we parse) are easy to audit.
"""
from __future__ import annotations


# ---- Mining (Layer E) ----

def pain_points(comment_lines: str, k: int) -> tuple[str, str]:
    system = (
        "You are an audience-research analyst. You read YouTube comments and surface the "
        "recurring questions and pain-points the audience expresses, in their own framing."
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


def patterns(title_lines: str) -> tuple[str, str]:
    system = (
        "You are a YouTube packaging analyst who clusters high-performing video titles into "
        "repeatable, namable formats."
    )
    prompt = (
        f"High-performing titles (with view multiplier vs the channel median):\n{title_lines}\n\n"
        "Cluster them into recurring formats. Return ONLY a JSON array:\n"
        '[{"label": "short format name", "description": "why it works, one sentence", '
        '"example_titles": ["exact title from the list", ...]}]\n'
        "JSON only."
    )
    return system, prompt


def source_summary(
    title: str, channel_name: str, transcript_excerpt: str, comment_lines: str
) -> tuple[str, str]:
    """Distill ONE video into a structured summary for a wiki source page (Brain Wiki ingest)."""
    system = (
        "You distill one YouTube video into a structured summary for a knowledge wiki: its "
        "hook, format, why it works, key takeaways, and audience signals drawn from comments."
    )
    prompt = (
        f'Video: "{title}" — {channel_name}\n\n'
        f'Transcript excerpt:\n"""\n{transcript_excerpt}\n"""\n\n'
        f"Top comments (with like counts):\n{comment_lines}\n\n"
        "Return ONLY JSON describing this video:\n"
        '{"hook": "how it opens, one line", '
        '"format": "short format name, e.g. listicle / tutorial / story / case-study", '
        '"why_it_works": "one sentence", '
        '"takeaways": ["concrete takeaway", ...], '
        '"audience_signals": [{"question": "a recurring pain-point/question from comments", '
        '"example": "short representative quote"}]}\n'
        "Keep every field short. JSON only, no prose."
    )
    return system, prompt


def style_card(channel_name: str, excerpt: str) -> tuple[str, str]:
    system = "You extract a concise, reusable style-card describing a YouTube creator's voice."
    prompt = (
        f'Transcript excerpts from "{channel_name}":\n"""\n{excerpt}\n"""\n\n'
        'Return ONLY JSON: {"tone": "...", "pacing": "...", '
        '"hooks": ["how they open videos", ...], '
        '"vocabulary": ["signature words/phrases", ...]}\n'
        "Keep each field short. JSON only."
    )
    return system, prompt


# ---- Generation (Layer G) ----

def ideas(context: str, n: int, guidance: str = "") -> tuple[str, str]:
    system = (
        "You are a YouTube content strategist. You propose specific, click-worthy video ideas "
        "grounded in proven demand, written in the creator's own style. You SYNTHESIZE — you "
        "never copy or lightly reword an existing video."
    )
    ask = f'\n\nUSER REQUEST: "{guidance.strip()}"\nHonor this request while staying grounded in the evidence above.' if guidance.strip() else ""
    prompt = (
        f"{context}{ask}\n\n"
        f"Propose {n} distinct, ORIGINAL video ideas. Treat the evidence above as proof of what "
        "the audience wants — NOT as templates. Hard rules:\n"
        "- Do NOT reuse, rephrase, or lightly tweak any single PROVEN TOPIC / existing title. "
        "Each idea must be clearly different from every title listed above.\n"
        "- Build each idea by COMBINING at least two signals (e.g. a proven format + an audience "
        "pain-point, or two topics) into a fresh angle the channel hasn't published yet.\n"
        "- Add a genuinely new hook, angle, or specific case/example — not just a synonym swap.\n"
        "- Each of the ideas must also differ from the others.\n"
        "Return ONLY a JSON array:\n"
        '[{"title": "specific, click-worthy, original title", "angle": "one-line angle — what makes it new", '
        '"format": "<one of the formats above, or other>", '
        '"evidence": ["which 2+ proven signals this combines"]}]\n'
        "Titles must be concrete (not generic) and original. JSON only."
    )
    return system, prompt


def refine_idea(
    prev_title: str, prev_angle: str, prev_score, drivers_hint: str, context: str, guidance: str
) -> tuple[str, str]:
    system = (
        "You are a YouTube strategist improving a video idea to maximize its predicted virality, "
        "while keeping it honest and grounded in the channels' proven demand."
    )
    ask = f' The user asked: "{guidance.strip()}".' if guidance.strip() else ""
    prompt = (
        f"{context}\n\n"
        f'Current idea: "{prev_title}" — {prev_angle}\n'
        f"Predicted virality: {prev_score}/100 — too low.\n"
        f"On these channels, videos that perform tend to use: {drivers_hint}.{ask}\n\n"
        "Propose ONE stronger idea that should score higher. Keep it ORIGINAL — it must NOT "
        "duplicate or lightly reword any existing title above; sharpen the hook/angle by "
        "combining proven signals, don't copy one. Return ONLY JSON:\n"
        '{"title": "...", "angle": "one-line angle — what makes it new", "format": "...", '
        '"evidence": ["which proven signals it combines"]}\n'
        "JSON only."
    )
    return system, prompt


def outline(title: str, angle: str, style: str) -> tuple[str, str]:
    system = "You are a long-form YouTube scriptwriter. You always outline in beats before writing."
    prompt = (
        f"Video title: {title}\nAngle: {angle}\n{style}\n\n"
        "Outline the video as ordered beats. Return ONLY a JSON array:\n"
        '[{"beat": "Hook|Setup|Body|CTA", "heading": "short label", '
        '"intent": "what this beat accomplishes"}]\n'
        "Include exactly 1 Hook, 1 Setup, 3-4 Body beats, and 1 CTA. JSON only."
    )
    return system, prompt


def expand(title: str, style: str, outline_summary: str, beat: str, heading: str, intent: str) -> tuple[str, str]:
    system = "You are a YouTube scriptwriter writing spoken narration in the creator's voice."
    prompt = (
        f"Video: {title}\n{style}\nFull outline:\n{outline_summary}\n\n"
        f"Write the script for THIS beat only — {beat}: {heading}.\n"
        f"Goal of the beat: {intent}\n"
        "Spoken narration, 80-160 words, no stage directions, no markdown headings. Plain text only."
    )
    return system, prompt


def description(title: str, angle: str, script_excerpt: str, niche: str | None, cta: str | None) -> tuple[str, str]:
    system = (
        "You write YouTube descriptions that rank in YouTube/Google search AND convert viewers "
        "into booked sales meetings. You balance SEO (natural keyword usage) with one clear, "
        "compelling call-to-action. You never keyword-stuff."
    )
    offer = cta.strip() if cta and cta.strip() else "a free strategy call (use [BOOKING LINK] as the placeholder)"
    prompt = (
        f"Video title: {title}\n"
        f"Angle: {angle}\n"
        f"Field / audience: {niche or 'infer from the script'}\n"
        f"Script excerpt:\n\"\"\"\n{script_excerpt[:1500]}\n\"\"\"\n\n"
        "GOAL: book a meeting with potential customers in this field.\n"
        f"Offer / CTA: {offer}\n\n"
        "Write the YouTube description:\n"
        "- First 2-3 lines: keyword-rich value summary (this is what ranks — put the main keyword early).\n"
        "- A clear CALL-TO-ACTION to book a meeting/call using the offer above (use [BOOKING LINK] if no link given).\n"
        "- 3-5 chapter timestamps if the script has clear sections (use 0:00 style).\n"
        "- End with 3-5 relevant, specific hashtags.\n"
        "Return ONLY the description text — no JSON, no preamble."
    )
    return system, prompt


def thumbnail_prompt(title: str, angle: str, script_excerpt: str) -> tuple[str, str]:
    """A ready-to-use image-generation prompt for the video's thumbnail (GenFlows-branded)."""
    system = (
        "You are a YouTube thumbnail art director for GenFlows, a B2B GTM-engineering agency. "
        "You write a single, vivid image-generation prompt (for tools like Midjourney/DALL·E) "
        "that makes a high-CTR thumbnail AND follows the GenFlows brand system exactly, so "
        "every video in the channel is instantly recognizable as part of the same series."
    )
    prompt = (
        f"Video title: {title}\n"
        f"Angle: {angle}\n"
        f"Script excerpt:\n\"\"\"\n{script_excerpt[:1200]}\n\"\"\"\n\n"
        "GENFLOWS BRAND SYSTEM (non-negotiable):\n"
        "- Background: deep navy #0A1F35, flat or with a subtle darker gradient / faint "
        "blueprint-grid texture.\n"
        "- ONE accent color only: orange #E67E22 — reserve it for the focal element "
        "(highlighted word, arrow, circle, glow). Never introduce any other accent hue.\n"
        "- Overlay text: 2-4 words MAX in a heavy geometric sans-serif (Manrope ExtraBold "
        "style), white #FFFFFF, with exactly ONE word in orange #E67E22.\n"
        "- Neutrals allowed for secondary detail: light gray #EDEFF7 / #D3D6E0.\n"
        "- Aesthetic: clean, premium, 'glass box' engineering look — pipelines, dashboards, "
        "diagrams or UI panels as glowing line-art; generous negative space, zero clutter.\n\n"
        "CTR RULES:\n"
        "- ONE bold focal point: an expressive face (tight crop, strong emotion, rim-lit "
        "against the navy) or a single striking object/diagram — never both competing.\n"
        "- Must read instantly at 120px wide on a phone: huge text, high contrast, no fine "
        "detail.\n"
        "- Composition: subject on one third, text on the other; keep the bottom-right corner "
        "clear (YouTube timestamp overlay).\n\n"
        "Write ONE image-generation prompt for a 16:9 (1280x720) thumbnail obeying ALL rules "
        "above. Specify: subject & composition, facial emotion if a person, the exact overlay "
        "text and which word is orange, colors by hex, lighting, and style. "
        "Return ONLY the prompt text — no preamble, no quotes."
    )
    return system, prompt


def polish(markdown: str) -> tuple[str, str]:
    system = "You are a sharp video editor improving a script for retention and flow."
    prompt = (
        "Tighten the following script for retention and flow WITHOUT changing its structure, "
        "headings, or meaning. Keep the markdown headings exactly. Return the full improved "
        f"markdown only:\n\n{markdown}"
    )
    return system, prompt
