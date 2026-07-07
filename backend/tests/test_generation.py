"""Insight mining + generation flow, validated with a FAKE LLM (no Claude needed).

The fake provider returns canned JSON/text routed by keywords in the prompt, so we
exercise the real parsing, persistence, virality-gating, and post-assembly logic
deterministically. Real runs swap in the Claude provider behind the same interface.

Run:  PYTHONPATH=. .venv/bin/python tests/test_generation.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


class FakeLLM:
    name = "fake"

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if "JSON array of up to" in prompt:  # pain-points
            return json.dumps([
                {"question": "How do I keep readers past the hook?", "frequency": 42, "example": "I always drop off"},
                {"question": "What hook works for boring niches?", "frequency": 30, "example": "my niche is dry"},
            ])
        if "Cluster them into recurring formats" in prompt:  # patterns
            return json.dumps([
                {"label": "X mistakes listicle", "description": "numbered pitfalls",
                 "example_titles": ["7 Mistakes Killing Your Posts"]},
            ])
        if "style-card" in (system or "").lower():  # style card
            return json.dumps({"tone": "punchy", "pacing": "daily", "hooks": ["cold open"], "vocabulary": ["actually"]})
        if "LinkedIn post ideas" in prompt:  # ideas
            return json.dumps([
                {"title": "7 Editing Mistakes Killing Your Retention", "angle": "fix them fast",
                 "format": "listicle", "evidence": ["proven listicle format", "retention pain-point"]},
                {"title": "a calm unstructured note about nothing", "angle": "chill",
                 "format": "other", "evidence": []},
            ])
        if "Plan the post as ordered sections" in prompt:  # outline
            return json.dumps([
                {"beat": "Hook", "heading": "Cold open", "intent": "grab attention"},
                {"beat": "Body", "heading": "Mistake 1", "intent": "first fix"},
                {"beat": "CTA", "heading": "Close", "intent": "ask one question"},
            ])
        if "Write the content for THIS section only" in prompt:  # expand
            return "Drafted lines for this section, in the creator's voice."
        if "Assemble the sections below" in prompt:  # assemble/polish
            return prompt.split("no preamble):\n\n", 1)[-1]  # echo hook + body unchanged
        if "Write the first comment" in prompt:  # first-comment CTA
            return "One more thing on retention: batching edits saved me hours.\n\nBook a free call: [BOOKING LINK]"
        return "{}"


class RefineLLM:
    """Initial ideas are weak (low virality); the refine step returns a strong listicle."""
    name = "refine-fake"

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if "stronger idea" in prompt:  # refine_idea
            return json.dumps({"title": "7 Editing Mistakes Killing Your Retention",
                               "angle": "fix them fast", "format": "listicle", "evidence": ["proven listicle"]})
        if "LinkedIn post ideas" in prompt:  # initial ideas (weak)
            return json.dumps([{"title": "a calm chat about editing today", "angle": "chill",
                               "format": "other", "evidence": []}])
        return "{}"


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


_VIRAL_TEXTS = [
    "7 Mistakes Killing Your Posts", "5 Ways to Boost Engagement", "9 Tips for Better Hooks",
    "3 Reasons Your Posts Flop", "6 Writing Rules I Swear By", "8 Signs Your Hook Is Weak",
]
_PLAIN_TEXTS = [
    "A calm note about my week", "My thoughts on the new update", "Behind the scenes of my setup",
    "Answering some questions", "Just hanging out and writing", "A quiet note about coffee",
]


def _seed_posts(session, total: int = 120):
    """Varied texts in both classes so the model learns the *feature* (numbered listicle),
    not one memorised point. ~1 in 4 is a viral listicle (10x reactions)."""
    from app.models import LinkedInPost

    start = datetime(2025, 1, 1)
    base = 500
    for i in range(total):
        viral = i % 4 == 0
        text = (_VIRAL_TEXTS if viral else _PLAIN_TEXTS)[i % 6]
        session.add(LinkedInPost(
            id=f"p{i}", author_id="ch", author_name="Test", text=text,
            reactions=base * (10 if viral else 1), published_at=start + timedelta(days=i),
        ))
    session.commit()


def _seed_comments(session):
    from app.models import PostComment

    for i in range(10):
        session.add(PostComment(post_id="p0", text=f"how do I keep readers hooked {i}?", likes=100 - i))
    session.commit()


def test_mine_pain_points_persists():
    from app import insights

    session = _session()
    _seed_posts(session)
    _seed_comments(session)

    rows = insights.mine_pain_points(session, niche=None, llm=FakeLLM())
    assert len(rows) == 2 and rows[0].frequency == 42, rows
    # stored + readable, ordered by frequency
    listed = insights.list_pain_points(session)
    assert listed[0].question.startswith("How do I keep readers"), listed
    print("pain-points mined + stored:", [(r.question[:30], r.frequency) for r in rows])


def test_ideas_are_virality_gated_and_ranked():
    from app.generation import ideas as ideas_gen

    session = _session()
    _seed_posts(session)  # trains the virality model (listicles viral)

    out = ideas_gen.generate_ideas(session, n=2, min_score=50, llm=FakeLLM())
    assert out["model_trained"] is True, out
    titles = [i["title"] for i in out["ideas"]]
    # The listicle should survive the gate and outrank the calm note (which is dropped < 50).
    assert titles and titles[0].startswith("7 Editing Mistakes"), out
    assert all(i["virality_score"] >= 50 for i in out["ideas"]), out
    assert "a calm unstructured note about nothing" not in titles, "low-virality idea should be gated out"
    print("ideas (gated):", [(i["title"][:34], i["virality_score"]) for i in out["ideas"]])


def test_post_assembles_outline_expand_polish():
    from app.generation import script as script_gen

    session = _session()
    out = script_gen.generate_script(session, title="7 Editing Mistakes Killing Your Retention",
                                     angle="fix them fast", llm=FakeLLM())
    assert out["sections"][0]["beat"] == "Hook"
    assert len(out["sections"]) == 3
    md = out["markdown"]
    assert "7 Editing Mistakes" in md, md
    assert "Drafted lines for this section" in md, md
    print("post sections:", [(s["beat"], s["heading"]) for s in out["sections"]])


def test_post_polish_flag_skips_assembly():
    from app.generation import script as script_gen

    session = _session()
    out = script_gen.generate_script(session, title="7 Editing Mistakes Killing Your Retention",
                                     polish=False, llm=FakeLLM())
    # Without polish, the post is just the joined sections — no assemble pass, no "Hook:" prefix.
    assert out["markdown"] == "\n\n".join(s["content"] for s in out["sections"]), out["markdown"]
    print("polish=False post:", out["markdown"][:60])


def test_first_comment_has_cta():
    from app.generation import script as script_gen

    session = _session()
    desc = script_gen.generate_description(
        session, title="7 Editing Mistakes", angle="fix fast",
        script_markdown="retention tips...", niche="editing",
        cta="Book a call: cal.com/me", llm=FakeLLM(),
    )
    assert "Book a free call" in desc or "BOOKING LINK" in desc, desc
    print("first comment:", desc.replace(chr(10), ' ').encode("ascii", "replace").decode()[:80])


def test_refine_loop_lifts_virality():
    from app.generation import refine

    session = _session()
    _seed_posts(session)  # trains the virality model (listicles viral)

    progress = []
    idea = refine.craft(
        session, llm=RefineLLM(), channel_id=None, niche=None,
        guidance="posts about editing", target_score=60.0, max_iters=4,
        on_progress=progress.append,
    )
    # Started weak, looped via refine, ended strong enough to proceed.
    assert idea["title"].startswith("7 Editing Mistakes"), idea
    assert idea["virality_score"] >= 60, idea
    assert any("try" in m for m in progress), progress
    print("refine loop:", [m.encode("ascii", "replace").decode() for m in progress])


if __name__ == "__main__":
    test_mine_pain_points_persists()
    test_ideas_are_virality_gated_and_ranked()
    test_post_assembles_outline_expand_polish()
    test_post_polish_flag_skips_assembly()
    test_first_comment_has_cta()
    test_refine_loop_lifts_virality()
    print("ALL GENERATION TESTS PASSED")
