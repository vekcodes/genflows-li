"""Novelty check for generated ideas. No network/LLM.

Run:  .venv/Scripts/python.exe tests/test_novelty.py
"""
from __future__ import annotations

import os

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_similarity_detects_near_copies():
    from app.generation import novelty

    a = "Scrape Every Google Maps Business with Clay"
    near = "Scrape Any Google Maps Business Using Clay"
    far = "Why Your Cold Emails Land in Spam (and the fix)"
    s_near = novelty.similarity(a, near)
    s_far = novelty.similarity(a, far)
    assert s_near > 0.7, s_near
    assert s_far < 0.4, s_far
    assert novelty.similarity(a, a) > 0.99
    print("similarity_detects_near_copies: ok  near=%.2f far=%.2f" % (s_near, s_far))


def test_max_similarity_and_empty():
    from app.generation import novelty

    existing = ["How to write cold emails", "Clay tutorial for beginners"]
    assert novelty.max_similarity("Clay tutorial for beginners", existing) > 0.99
    assert novelty.max_similarity("Totally unrelated cooking video", existing) < 0.4
    assert novelty.max_similarity("anything", []) == 0.0
    print("max_similarity_and_empty: ok")


def test_existing_titles_pulls_videos_and_queue():
    from app.generation import novelty
    from app.models import ContentItem, Video

    s = _session()
    s.add(Video(id="v1", channel_id="UCx", title="Existing scraped video", views=10, duration_sec=60))
    s.add(ContentItem(batch_id="b1", title="A queued idea", status="proposed"))
    s.commit()
    titles = novelty.existing_titles(s)
    assert "Existing scraped video" in titles
    assert "A queued idea" in titles
    # channel filter narrows the video side
    assert novelty.existing_titles(s, channel_id="UCother").count("Existing scraped video") == 0
    print("existing_titles_pulls_videos_and_queue: ok")


def test_stopwords_dont_inflate_similarity():
    from app.generation import novelty

    # Same filler words, totally different substance -> should be low.
    a = "How to grow your YouTube channel with AI"
    b = "How to cook the best pasta for your family"
    assert novelty.similarity(a, b) < 0.45
    print("stopwords_dont_inflate_similarity: ok")


if __name__ == "__main__":
    test_similarity_detects_near_copies()
    test_max_similarity_and_empty()
    test_existing_titles_pulls_videos_and_queue()
    test_stopwords_dont_inflate_similarity()
    print("ALL NOVELTY TESTS PASSED")
