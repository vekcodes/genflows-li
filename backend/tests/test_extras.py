"""Demand parsing, vector chunking/search, and API-key auth — no network/LLM."""
from __future__ import annotations

import os

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


# ---- demand ----

def test_trend_direction():
    from app.demand import trend_direction

    assert trend_direction([10, 12, 20, 40, 60]) == "rising"
    assert trend_direction([60, 50, 30, 20, 10]) == "falling"
    assert trend_direction([50, 51, 49, 50, 50]) == "flat"
    print("trend_direction: ok")


def test_parse_suggest():
    from app.demand import parse_suggest

    assert parse_suggest(["hooks", ["youtube hooks", "hooks examples"]]) == ["youtube hooks", "hooks examples"]
    assert parse_suggest(["x"]) == []
    assert parse_suggest("garbage") == []
    print("parse_suggest: ok")


# ---- vector store ----

def test_chunking_and_search():
    from app import vectorstore

    assert len(vectorstore.chunk_text("a" * 4000, max_chars=1600, overlap=200)) >= 3
    assert vectorstore.chunk_text("") == []

    session = _session()
    vectorstore.index_video(session, "v1", "How to improve video retention and keep viewers watching longer.")
    vectorstore.index_video(session, "v2", "A relaxing recipe for homemade sourdough bread and coffee.")
    session.commit()

    hits = vectorstore.search(session, "retention tips", k=2)
    assert hits and hits[0]["video_id"] == "v1", hits
    print("vector search: ok ->", hits[0]["video_id"], hits[0]["score"])


def test_content_gaps():
    from app import brain, vectorstore
    from app.models import PainPoint

    session = _session()
    # The corpus covers retention, NOT microphones.
    vectorstore.index_video(session, "v1", "How to improve video retention and keep viewers watching.")
    session.add(PainPoint(question="How do I improve retention?", frequency=50))
    session.add(PainPoint(question="What is the best microphone for podcasts?", frequency=40))
    session.commit()

    gaps = brain.content_gaps(session, coverage_threshold=0.05)
    by_q = {g["question"]: g for g in gaps}
    assert by_q["What is the best microphone for podcasts?"]["covered"] is False, gaps
    assert by_q["How do I improve retention?"]["coverage"] > by_q["What is the best microphone for podcasts?"]["coverage"], gaps
    # uncovered, high-frequency gap should sort first
    assert gaps[0]["covered"] is False, gaps
    print("content gaps: ok ->", [(g["question"][:24], g["covered"], g["coverage"]) for g in gaps])


# ---- API key auth ----

def test_api_key_auth():
    import warnings; warnings.filterwarnings("ignore")
    os.environ["BRAIN_API_KEY"] = "secret123"
    os.environ["BRAIN_DATABASE_URL"] = "sqlite:///./_auth_test.db"
    from app.config import get_settings
    get_settings.cache_clear()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        assert c.get("/health").status_code == 200          # public
        assert c.get("/sources").status_code == 401          # protected, no key
        assert c.get("/sources", headers={"x-api-key": "secret123"}).status_code == 200
        assert c.get("/sources", headers={"x-api-key": "wrong"}).status_code == 401
    os.environ.pop("BRAIN_API_KEY", None)
    get_settings.cache_clear()
    print("api-key auth: ok")


if __name__ == "__main__":
    test_trend_direction()
    test_parse_suggest()
    test_chunking_and_search()
    test_content_gaps()
    test_api_key_auth()
    print("ALL EXTRAS TESTS PASSED")
