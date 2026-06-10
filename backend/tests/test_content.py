"""Agentic content engine — validated with a FAKE LLM (no Claude, no network).

Covers the loop end to end: generate a full content package into the queue, decline with a
reason → a replacement is crafted that actually saw the reason, and mark-published → measure the
real outlier multiplier → reward + learning memory. The virality gate itself is covered by
test_virality.py.

Run:  PYTHONPATH=. .venv/Scripts/python.exe tests/test_content.py
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


class FakeLLM:
    """Routes canned output by prompt markers and records every prompt it saw."""

    name = "fake"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        if "stronger idea" in prompt:  # refine_idea
            return json.dumps({"title": "7 Editing Mistakes Killing Your Retention",
                               "angle": "fix them fast", "format": "listicle", "evidence": ["proven listicle"]})
        if "Propose" in prompt and "video ideas" in prompt:  # ideas
            return json.dumps([
                {"title": "7 Editing Mistakes Killing Your Retention", "angle": "fix them fast",
                 "format": "listicle", "evidence": ["proven listicle format"]},
            ])
        if "Outline the video" in prompt:  # outline
            return json.dumps([
                {"beat": "Hook", "heading": "Cold open", "intent": "grab attention"},
                {"beat": "Body", "heading": "Mistake 1", "intent": "first fix"},
                {"beat": "CTA", "heading": "Close", "intent": "subscribe"},
            ])
        if "Write the script for THIS beat only" in prompt:  # expand
            return "Spoken narration for this beat."
        if "Tighten the following script" in prompt:  # polish
            return prompt.split("markdown only:\n\n", 1)[-1]
        if "Write the YouTube description" in prompt:  # description
            return "Learn retention editing fast.\n\n👉 Book a call: [BOOKING LINK]\n\n#editing"
        if "image-generation prompt for the thumbnail" in prompt:  # thumbnail
            return "Close-up shocked editor, bold text 'STOP THIS', high-contrast orange/navy, dramatic light."
        return "{}"


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


# ---- generate ----

def test_generate_batch_full_package():
    from app import agent
    from app.models import ContentStatus

    session = _session()
    profile = agent.get_profile(session)
    profile.offer = "Book a free editing audit: cal.com/me"
    session.add(profile); session.commit()

    items = agent.generate_batch(session, llm=FakeLLM(), n=2, refresh=False)
    assert len(items) == 2, len(items)
    for it in items:
        assert it.status == ContentStatus.proposed
        assert it.title and it.script_markdown and it.description and it.thumbnail_prompt
        assert it.sections, "script sections missing"
        assert it.batch_id == items[0].batch_id  # same batch
    print("generate_batch (full package): ok")


# ---- decline → learn → regenerate ----

def test_decline_regenerates_with_reason():
    from app import agent
    from app.models import ContentFeedback, ContentItem, ContentStatus
    from sqlmodel import select

    session = _session()
    agent.get_profile(session)
    [item] = agent.generate_batch(session, llm=FakeLLM(), n=1, refresh=False)

    llm = FakeLLM()
    reason = "too generic — needs a concrete, niche-specific angle"
    repl = agent.decline(session, item.id, reason, llm=llm)

    session.refresh(item)
    assert item.status == ContentStatus.declined and item.declined_reason == reason
    assert repl.status == ContentStatus.proposed
    assert repl.regenerated_from_id == item.id
    assert repl.batch_id == item.batch_id

    # feedback logged
    fb = session.exec(select(ContentFeedback).where(ContentFeedback.kind == "decline")).all()
    assert fb and reason in fb[0].reason

    # the decline reason actually reached the LLM (proves the learning context was used)
    assert any(reason in p for p in llm.prompts), "decline reason was not fed into generation"
    print("decline -> regenerate (learns reason): ok")


# ---- publish → measure → reward ----

def test_publish_measures_reward_and_memory():
    from app import agent
    from app.models import ContentFeedback, ContentStatus, Video
    from sqlmodel import select

    session = _session()
    # The creator's channel baseline: median of [800,1000,9000] = 1000; the published video is 9x.
    for vid, views in [("base_a", 800), ("base_b", 1000), ("myvid000001", 9000)]:
        session.add(Video(id=vid, channel_id="UC_me", channel_name="Me", title=vid, views=views))
    session.commit()

    [item] = agent.generate_batch(session, llm=FakeLLM(), n=1, refresh=False)
    agent.approve(session, item.id)

    # video already in the lake → no network fetch needed
    out = agent.mark_published(session, item.id, url="https://youtu.be/myvid000001", video_id="myvid000001")
    assert out.status == ContentStatus.scored, out.status
    assert out.actual_multiplier == 9.0
    assert out.performed is True
    assert out.reward == 9.0

    perf = session.exec(select(ContentFeedback).where(ContentFeedback.kind == "performance")).all()
    assert perf, "no performance feedback recorded"

    # the win shows up in the learning memory fed to future generations
    learned = agent._learning_context(session)
    assert "WHAT WORKED" in learned and item.title in learned
    print("publish -> reward + memory: ok")


if __name__ == "__main__":
    test_generate_batch_full_package()
    test_decline_regenerates_with_reason()
    test_publish_measures_reward_and_memory()
    print("\nall content-engine tests passed")
