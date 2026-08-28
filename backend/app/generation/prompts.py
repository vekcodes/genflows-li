"""Prompt builders for LinkedIn mining + generation. Each returns (system, prompt).

Kept in one place so the contracts (and the JSON shapes we parse) are easy to audit.
"""
from __future__ import annotations

# Injected into every prompt that writes reader-facing post text. The point is to kill
# the tells that make a post read as machine-written, without banning the formats the
# engagement model actually rewards (listicles, numbers, contrarian angles are fine).
HUMAN_VOICE = (
    "WRITE LIKE A HUMAN — hard rules:\n"
    "- Sound like one person talking to a colleague. Use contractions. Plain words over impressive ones.\n"
    "- Vary sentence length: mix a longer sentence in with the short ones. A wall of clipped "
    "one-line punches is the biggest AI tell.\n"
    "- Banned words/phrases: game-changer, Let that sink in, Read that again, Here's the kicker, "
    "the harsh truth, in today's fast-paced world, in today's digital landscape, unlock, unleash, "
    "elevate, delve, leverage (as a verb), navigate the landscape, secret sauce, "
    "take it to the next level, I'll say it louder, double-edged sword.\n"
    "- Banned constructions: the 'It's not about X. It's about Y.' snap; 'X isn't just Y — it's Z'; "
    "triple fragments ('Faster. Cheaper. Better.'); opening with 'Imagine' or 'Picture this'.\n"
    "- At most ONE question in the whole post. Never 'Agree?', 'Thoughts?', 'Who's with me?'.\n"
    "- At most one em-dash in the whole post. No semicolons.\n"
    "- No emoji unless the creator's style card shows they use them — then at most 2.\n"
    "- Specifics over abstractions: real numbers, tools, timeframes, dollar amounts. NEVER invent "
    "stats or client stories — if a concrete detail is needed but unknown, leave a placeholder "
    "like [ADD SPECIFIC: your number/example here] for the creator to fill in.\n"
    "- Plain text only: no markdown, no bold, no headings, no 'Tip 1:' labels.\n"
    "- Hashtags: none, or up to 3 on the last line only."
)


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
        "Hooks must be concrete and original, and must sound like a person wrote them — "
        "specific claims or numbers, not clickbait formulas ('This will change everything', "
        "'Nobody talks about this'). JSON only."
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


def expand_section(
    title: str, angle: str, style: str, outline_summary: str, beat: str, heading: str, intent: str
) -> tuple[str, str]:
    system = (
        "You are a LinkedIn ghostwriter writing in the creator's authentic voice. "
        "Your drafts read like the creator typed them, not like AI output."
    )
    length = {
        "Hook": "1-2 short lines (the hook itself, nothing more)",
        "CTA": "1-2 sentences",
    }.get(beat, "40-90 words")
    prompt = (
        f"Post hook: {title}\nAngle: {angle}\n{style}\nFull outline:\n{outline_summary}\n\n"
        f"Write the content for THIS section only — {beat}: {heading}.\n"
        f"Goal of the section: {intent}\n"
        f"Length: {length}. Cover ONLY this section's point — don't restate the hook and don't "
        "wrap up (other sections handle that). Short paragraphs (1-2 sentences) with a blank "
        f"line between them.\n\n{HUMAN_VOICE}"
    )
    return system, prompt


def assemble_post(title: str, sections: list[dict], style: str) -> tuple[str, str]:
    """Assemble sections into a final LinkedIn post with a light, voice-preserving edit."""
    body = "\n\n".join(s.get("content", "") for s in sections if s.get("content"))
    system = (
        "You are an editor assembling a LinkedIn post from drafted sections. You protect the "
        "writer's voice — you cut and stitch, you don't rewrite into generic LinkedIn-speak."
    )
    prompt = (
        f"{style}\n\n"
        "Assemble the sections below into one LinkedIn post. Editing rules:\n"
        "- Keep the writer's wording wherever possible; only fix seams between sections.\n"
        "- Cut anything repeated across sections — say each thing once.\n"
        "- The hook goes on its own line (first 2 lines are all people see before 'see more').\n"
        "- Blank line between paragraphs. Target 120-220 words total; when in doubt, cut.\n"
        "- End with the CTA section's close — don't add an extra question on top of it.\n"
        f"\n{HUMAN_VOICE}\n\n"
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
        "- Written like the creator typed it on their phone: casual, contractions, no emoji, "
        "no 'game-changer'/'unlock'-style marketing words\n"
        "Return ONLY the comment text — no preamble, no JSON."
    )
    return system, prompt


def image_prompt(title: str, angle: str, post_text: str) -> tuple[str, str]:
    """Brief for the post visual, as JSON: a text-free render prompt + the overlay headline.

    The render prompt deliberately forbids letters in the generated image. Open text-to-image
    models (FLUX included) garble typography, and LinkedIn images live or die on a readable
    headline — so the app burns the 2-4 word overlay on afterwards, in the exact brand fonts
    and hexes, over a clean generated background.
    """
    system = (
        "You are a LinkedIn visual content director for GenFlows, a B2B GTM-engineering agency. "
        "You brief a text-to-image model (FLUX) and follow the GenFlows brand system exactly. "
        "You always answer with valid JSON only."
    )
    prompt = (
        f"Post hook: {title}\n"
        f"Angle: {angle}\n"
        f"Post excerpt:\n\"\"\"\n{post_text[:800]}\n\"\"\"\n\n"
        "GENFLOWS BRAND SYSTEM (non-negotiable):\n"
        "- Background: deep navy #0A1F35, flat or subtle gradient.\n"
        "- ONE accent color only: orange #E67E22 for the focal element.\n"
        "- Aesthetic: clean, premium, engineering/GTM look - pipelines, dashboards, "
        "flow diagrams as glowing line-art; generous negative space, especially in the "
        "lower third (a headline is composited there afterwards).\n"
        "- Square 1:1 composition, LinkedIn feed-ready.\n\n"
        "CRITICAL: the generated image must contain NO text, NO letters, NO numbers, NO words, "
        "NO logos, NO watermarks, NO UI labels - the headline is added later by the app. "
        "Say so explicitly at the end of the render prompt.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "render_prompt": "one vivid paragraph for the image model: subject, composition, '
        'lighting, materials, colors by hex, negative space in the lower third, and the '
        'no-text/no-logo instruction",\n'
        '  "overlay_text": "the headline burned onto the image - 2 to 4 words, uppercase, '
        'concrete, earns the click",\n'
        '  "accent_word": "exactly one word copied verbatim from overlay_text, rendered in '
        'orange #E67E22"\n'
        "}"
    )
    return system, prompt


def polish(text: str) -> tuple[str, str]:
    system = (
        "You are a sharp editor. Your job is to make a LinkedIn post read like its author "
        "wrote it on a good day — never to make it sound more like marketing."
    )
    prompt = (
        "Tighten the following LinkedIn post WITHOUT changing its structure or meaning. "
        "Remove anything that reads as AI-written per the rules below. Ensure white space "
        "between short paragraphs and keep the hook on its own line.\n\n"
        f"{HUMAN_VOICE}\n\n"
        f"Return the full improved post text only:\n\n{text}"
    )
    return system, prompt
