"""Brain Wiki ingest — prototype, validated with a FAKE LLM (no Claude, no network).

Seeds a tiny Raw Lake (one channel, three videos so a median exists + one clear outlier),
ingests the outlier into a temp wiki, and asserts the pages, citations, frontmatter, index,
and log are produced — and that re-ingesting compounds rather than duplicates.

Run:  PYTHONPATH=. .venv/Scripts/python.exe tests/test_wiki.py
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
        if "Return ONLY JSON describing this video" in prompt:  # source_summary
            return json.dumps({
                "hook": "Cold open on the single biggest editing mistake.",
                "format": "Mistakes listicle",
                "why_it_works": "Names a concrete enemy the viewer can fix today.",
                "takeaways": ["Cut the first 5 seconds", "Tighten B-roll to the beat"],
                "audience_signals": [
                    {"question": "How do I keep retention past the intro?", "example": "I always drop off at 30s"},
                ],
            })
        if "style-card" in (system or "").lower() or '"tone"' in prompt:  # style_card
            return json.dumps({"tone": "punchy", "pacing": "fast", "hooks": ["cold open"], "vocabulary": ["actually"]})
        return "{}"


def _session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed(session):
    from app.models import Comment, Transcript, Video

    # Three videos on one channel: median views = 1000, so the 9000-view one is ~9x.
    for vid, views in [("base1", 800), ("base2", 1000), ("hit01", 9000)]:
        session.add(Video(id=vid, channel_id="UC_test", channel_name="EditPro", title=f"Video {vid}", views=views))
    session.add(Transcript(video_id="hit01", text="Today the biggest editing mistake is a slow intro. " * 50))
    session.add(Comment(video_id="hit01", text="I always drop off at 30s, how do I keep retention?", likes=120))
    session.commit()


def test_ingest_creates_and_compounds():
    from app import wiki
    from app.wiki.store import WikiStore

    session = _session()
    _seed(session)
    llm = FakeLLM()

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(tmp)
        res = wiki.ingest_video(session, store, "hit01", today=date(2026, 6, 3), llm=llm)

        # multiplier comes from the DB (9000 / median 1000 = 9.0), not the LLM
        assert res.multiplier == 9.0, res.multiplier

        # expected pages exist
        for rel in ["sources/hit01.md", "channels/editpro.md", "formats/mistakes-listicle.md", "index.md"]:
            assert store.exists(rel), f"missing {rel}"

        src_fm, src_body = store.read("sources/hit01.md")
        assert src_fm["multiplier"] == 9.0
        assert src_fm["video_id"] == "hit01"
        assert "`hit01`" in src_body  # cited
        assert "[[channels/editpro]]" in src_body  # cross-linked

        fmt_fm, _ = store.read("formats/mistakes-listicle.md")
        assert fmt_fm["avg_multiplier"] == 9.0
        assert fmt_fm["source_count"] == 1

        ch_fm, _ = store.read("channels/editpro.md")
        assert ch_fm["outliers"][0]["video_id"] == "hit01"
        assert ch_fm["source_count"] == 1

        # an audience page was created from the comment signal
        aud = [p for p in store.list("audience")]
        assert aud, "no audience page created"

        # index lists the source with its multiplier; log recorded the ingest
        _, idx_body = store.read("index.md")
        assert "[[sources/hit01]]" in idx_body and "9.0×" in idx_body
        log_text = (store.root / "log.md").read_text(encoding="utf-8")
        assert "ingest | EditPro" in log_text and "(9.0×)" in log_text

        # re-ingest the SAME video → compounds in place, no duplicate example rows
        wiki.ingest_video(session, store, "hit01", today=date(2026, 6, 4), llm=llm)
        fmt_fm2, _ = store.read("formats/mistakes-listicle.md")
        assert fmt_fm2["source_count"] == 1, "re-ingest must not duplicate"
        ch_fm2, _ = store.read("channels/editpro.md")
        assert ch_fm2["source_count"] == 1
        assert ch_fm2["updated"] == "2026-06-04"  # updated in place

    print("wiki ingest: ok")


def test_store_rejects_unsafe_paths():
    from app.wiki.store import WikiStore

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(tmp)
        for bad in ["../escape.md", "/etc/passwd.md", "sources/../../x.md", "no_ext"]:
            try:
                store.write(bad, {}, "x")
            except ValueError:
                continue
            raise AssertionError(f"unsafe path accepted: {bad}")
    print("store path safety: ok")


def test_backfill_and_counts():
    from app import wiki
    from app.wiki import read as wiki_read
    from app.wiki.store import WikiStore

    session = _session()
    _seed(session)  # base1, base2, hit01

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(tmp)
        results = wiki.backfill(session, store, today=date(2026, 6, 3), limit=2, llm=FakeLLM())
        assert len(results) == 2, len(results)  # capped at 2 of 3 videos
        assert wiki_read.counts(store)["sources"] == 2

        # idempotent: a second backfill ingests only the remaining one
        more = wiki.backfill(session, store, today=date(2026, 6, 3), limit=10, llm=FakeLLM())
        assert len(more) == 1
        assert wiki_read.counts(store)["sources"] == 3
    print("backfill + counts: ok")


if __name__ == "__main__":
    test_ingest_creates_and_compounds()
    test_store_rejects_unsafe_paths()
    test_backfill_and_counts()
    print("\nall wiki tests passed")
