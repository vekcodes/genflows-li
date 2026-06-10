"""Insight mining + generation flow, validated with a FAKE LLM (no Claude needed).

The fake provider returns canned JSON/text routed by keywords in the prompt, so we
exercise the real parsing, persistence, virality-gating, and script-assembly logic
deterministically. Real runs swap in the Claude provider behind the same interface.

Run:  PYTHONPATH=. .venv/Scripts/python.exe tests/test_generation.py
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
                {"question": "How do I keep retention past the intro?", "frequency": 42, "example": "I always drop off"},
                {"question": "What hook works for boring topics?", "frequency": 30, "example": "my niche is dry"},
            ])
        if "Cluster them into recurring formats" in prompt:  # patterns
            return json.dumps([
                {"label": "X mistakes listicle", "description": "numbered pitfalls",
                 "example_titles": ["7 Mistakes Killing Your Edits"]},
            ])
        if '"tone"' in prompt and "style-card" in (system or "").lower():  # style card
            return json.dumps({"tone": "punchy", "pacing": "fast", "hooks": ["cold open"], "vocabulary": ["actually"]})
        if "Propose" in prompt and "video ideas" in prompt:  # ideas
            return json.dumps([
                {"title": "7 Editing Mistakes Killing Your Retention", "angle": "fix them fast",
                 "format": "listicle", "evidence": ["proven listicle format"]},
                {"title": "a calm unstructured vlog about nothing", "angle": "chill",
                 "format": "other", "evidence": []},
            ])
        if "Outline the video" in prompt:  # outline
            return json.dumps([
                {"beat": "Hook", "heading": "Cold open", "intent": "grab attention"},
                {"beat": "Body", "heading": "Mistake 1", "intent": "first fix"},
                {"beat": "CTA", "heading": "Close", "intent": "subscribe"},
            ])
        if "Write the script for THIS beat only" in prompt:  # expand
            return "Spoken narration for this beat, in the creator's voice."
        if "Tighten the following script" in prompt:  # polish
            return prompt.split("markdown only:\n\n", 1)[-1]  # echo unchanged
        if "YouTube description" in prompt:  # description / CTA
            return "Learn retention editing fast.\n\n👉 Book a free call: [BOOKING LINK]\n\n#editing #youtube"
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
        if "video ideas" in prompt:  # initial ideas (weak)
            return json.dumps([{"title": "a calm chat about editing today", "angle": "chill",
                               "format": "other", "evidence": []}])
        return "{}"


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


_VIRAL_TITLES = [
    "7 Mistakes Killing Your Edits", "5 Ways to Boost Retention", "9 Tips for Better Hooks",
    "3 Reasons Your Videos Flop", "6 Editing Rules I Swear By", "8 Signs Your Hook Is Weak",
]
_PLAIN_TITLES = [
    "A calm chat about my week", "My thoughts on the new update", "Behind the scenes of my setup",
    "Answering some questions", "Just hanging out and editing", "A quiet vlog about coffee",
]


def _seed_videos(session, total: int = 120):
    """Varied titles in both classes so the model learns the *feature* (numbered listicle),
    not one memorised point. ~1 in 4 is a viral listicle (10x views)."""
    from app.models import Video

    start = datetime(2025, 1, 1)
    base = 50_000
    for i in range(total):
        viral = i % 4 == 0
        title = (_VIRAL_TITLES if viral else _PLAIN_TITLES)[i % 6]
        session.add(Video(
            id=f"v{i}", channel_id="ch", channel_name="Test", title=title,
            views=base * (10 if viral else 1), duration_sec=600, published_at=start + timedelta(days=i),
        ))
    session.commit()


def _seed_comments(session):
    from app.models import Comment

    for i in range(10):
        session.add(Comment(video_id="v0", text=f"how do I keep retention {i}?", likes=100 - i))
    session.commit()


def test_mine_pain_points_persists():
    from app import insights

    session = _session()
    _seed_videos(session)
    _seed_comments(session)

    rows = insights.mine_pain_points(session, niche=None, llm=FakeLLM())
    assert len(rows) == 2 and rows[0].frequency == 42, rows
    # stored + readable, ordered by frequency
    listed = insights.list_pain_points(session)
    assert listed[0].question.startswith("How do I keep retention"), listed
    print("pain-points mined + stored:", [(r.question[:30], r.frequency) for r in rows])


def test_ideas_are_virality_gated_and_ranked():
    from app.generation import ideas as ideas_gen

    session = _session()
    _seed_videos(session)  # trains the virality model (listicles viral)

    out = ideas_gen.generate_ideas(session, n=2, min_score=50, llm=FakeLLM())
    assert out["model_trained"] is True, out
    titles = [i["title"] for i in out["ideas"]]
    # The listicle should survive the gate and outrank the calm vlog (which is dropped < 50).
    assert titles and titles[0].startswith("7 Editing Mistakes"), out
    assert all(i["virality_score"] >= 50 for i in out["ideas"]), out
    assert "a calm unstructured vlog about nothing" not in titles, "low-virality idea should be gated out"
    print("ideas (gated):", [(i["title"][:34], i["virality_score"]) for i in out["ideas"]])


def test_script_assembles_outline_expand_polish():
    from app.generation import script as script_gen

    session = _session()
    out = script_gen.generate_script(session, title="7 Editing Mistakes Killing Your Retention", llm=FakeLLM())
    assert out["sections"][0]["beat"] == "Hook"
    assert len(out["sections"]) == 3
    md = out["markdown"]
    assert md.startswith("# 7 Editing Mistakes")
    assert "## Hook — Cold open" in md and "## CTA — Close" in md
    assert "Spoken narration for this beat" in md
    print("script sections:", [(s["beat"], s["heading"]) for s in out["sections"]])


def test_description_has_cta_and_seo():
    from app.generation import script as script_gen

    session = _session()
    desc = script_gen.generate_description(
        session, title="7 Editing Mistakes", angle="fix fast",
        script_markdown="# x\nretention tips...", niche="editing",
        cta="Book a call: cal.com/me", llm=FakeLLM(),
    )
    assert "Book a free call" in desc or "BOOKING LINK" in desc, desc
    assert "#" in desc, desc  # has hashtags (SEO)
    print("description:", desc.replace(chr(10), ' ').encode("ascii", "replace").decode()[:80])


def test_refine_loop_lifts_virality():
    from app.generation import refine

    session = _session()
    _seed_videos(session)  # trains the virality model (listicles viral)

    progress = []
    idea = refine.craft(
        session, llm=RefineLLM(), channel_id=None, niche=None,
        guidance="scripts about editing", target_score=60.0, max_iters=4,
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
    test_script_assembles_outline_expand_polish()
    test_description_has_cta_and_seo()
    test_refine_loop_lifts_virality()
    print("ALL GENERATION TESTS PASSED")
