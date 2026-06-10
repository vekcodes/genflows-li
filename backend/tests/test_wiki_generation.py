"""Phase 3 — generation reads the Brain Wiki when enabled, falls back to DB when not.

Validates the context seam in generation/ideas.py + script.py deterministically (fake LLM,
in-memory DB, temp wiki). The virality gate is unchanged and covered by test_virality.py.

Run:  PYTHONPATH=. .venv/Scripts/python.exe tests/test_wiki_generation.py
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


class FakeLLM:
    name = "fake"

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if "Return ONLY JSON describing this video" in prompt:
            return json.dumps({
                "hook": "Cold open on the biggest editing mistake.",
                "format": "Mistakes listicle",
                "why_it_works": "Names a concrete enemy.",
                "takeaways": ["Cut the intro"],
                "audience_signals": [{"question": "How do I keep retention past the intro?", "example": "I drop off at 30s"}],
            })
        if "style-card" in (system or "").lower() or '"tone"' in prompt:
            return json.dumps({"tone": "punchy", "pacing": "fast", "hooks": ["cold open"], "vocabulary": ["actually"]})
        return "{}"


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_lake(session):
    from app.models import Comment, Transcript, Video

    for vid, views in [("base1", 800), ("base2", 1000), ("hit01", 9000)]:
        session.add(Video(id=vid, channel_id="UC_test", channel_name="EditPro", title=f"Video {vid}", views=views))
    session.add(Transcript(video_id="hit01", text="The biggest editing mistake is a slow intro. " * 40))
    session.add(Comment(video_id="hit01", text="I drop off at 30s, how do I keep retention?", likes=99))
    session.commit()


def _enable_wiki(flag: bool):
    from app.config import get_settings

    os.environ["BRAIN_BRAIN_WIKI_ENABLED"] = "true" if flag else "false"
    get_settings.cache_clear()


def test_context_prefers_wiki_when_enabled():
    from app import wiki
    from app.generation import ideas
    from app.wiki.store import WikiStore

    session = _session()
    _seed_lake(session)

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(tmp)
        wiki.ingest_video(session, store, "hit01", today=date(2026, 6, 3), llm=FakeLLM())

        _enable_wiki(True)
        ctx = ideas._build_context(session, channel_id="UC_test", niche=None, query="retention", store=store)

        # qualitative layer comes from the wiki pages
        assert "Mistakes listicle" in ctx, ctx
        assert "How do I keep retention past the intro?" in ctx
        assert "tone: punchy" in ctx
        # quantitative layer still present (from the DB)
        assert "PROVEN TOPICS" in ctx

        # script style line also resolves from the wiki
        from app.generation import script
        line = script._style_line(session, "UC_test", store=store)
        assert "tone: punchy" in line and "pacing: fast" in line

    _enable_wiki(False)
    print("wiki-context (enabled): ok")


def test_context_falls_back_to_db_when_disabled():
    from app.generation import ideas
    from app.models import FormatPattern, PainPoint, StyleCard

    session = _session()
    _seed_lake(session)
    # DB insight tables (the legacy path)
    session.add(StyleCard(channel_id="UC_test", channel_name="EditPro", tone="dry", pacing="slow",
                          hooks=["question"], vocabulary=["basically"]))
    session.add(FormatPattern(niche=None, label="DB Tutorial", description="step-by-step", avg_multiplier=4.0,
                              example_video_ids=["hit01"]))
    session.add(PainPoint(niche=None, question="DB pain question?", frequency=7))
    session.commit()

    _enable_wiki(False)
    ctx = ideas._build_context(session, channel_id="UC_test", niche=None, query="retention")
    assert "DB Tutorial" in ctx and "DB pain question?" in ctx and "tone: dry" in ctx, ctx
    assert "Mistakes listicle" not in ctx
    print("db-fallback (disabled): ok")


if __name__ == "__main__":
    test_context_prefers_wiki_when_enabled()
    test_context_falls_back_to_db_when_disabled()
    print("\nall phase-3 tests passed")
