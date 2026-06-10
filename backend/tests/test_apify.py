"""Apify backend mapping + scraper/transcript fallback — no network (run_actor is swapped out).

Run:  .venv/Scripts/python.exe tests/test_apify.py     (or via pytest)
"""
from __future__ import annotations

import os

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


# ---- tiny manual monkeypatch (the suite runs as plain scripts, no pytest fixtures) ----

class _Swap:
    """Temporarily set object attributes / env vars, restoring them on exit."""

    def __init__(self):
        self._attrs: list[tuple[object, str, object, bool]] = []
        self._env: list[tuple[str, str | None]] = []

    def attr(self, obj, name, value):
        had = hasattr(obj, name)
        self._attrs.append((obj, name, getattr(obj, name, None), had))
        setattr(obj, name, value)

    def env(self, name, value):
        self._env.append((name, os.environ.get(name)))
        os.environ[name] = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        from app.config import get_settings

        for obj, name, old, had in reversed(self._attrs):
            if had:
                setattr(obj, name, old)
            else:
                delattr(obj, name)
        for name, old in reversed(self._env):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        get_settings.cache_clear()


def _enable_apify(swap: _Swap):
    from app.config import get_settings

    swap.env("BRAIN_SCRAPE_PROVIDER", "apify")
    swap.env("BRAIN_APIFY_TOKEN", "test-token")
    get_settings.cache_clear()


# ---- duration / date parsing ----

def test_to_seconds():
    from app.ingestion import apify

    assert apify._to_seconds(90) == 90
    assert apify._to_seconds("1:30") == 90
    assert apify._to_seconds("1:02:03") == 3723
    assert apify._to_seconds("PT1M23S") == 83
    assert apify._to_seconds(None) == 0
    assert apify._to_seconds("garbage") == 0
    print("to_seconds: ok")


def test_to_upload_date():
    from app.ingestion import apify

    assert apify._to_upload_date("2026-06-04T10:00:00Z") == "20260604"
    assert apify._to_upload_date("2026-06-04") == "20260604"
    assert apify._to_upload_date(None) is None
    assert apify._to_upload_date("not a date") is None
    print("to_upload_date: ok")


# ---- video mapping → yt-dlp shape → map_signals ----

def test_fetch_video_maps_into_signals():
    from app.ingestion import apify, scraper

    item = {
        "id": "abc12345678",
        "channelId": "UC_chan",
        "channelName": "Eric N",
        "title": "Clay tutorial",
        "text": "a description",
        "viewCount": 27000,
        "likes": 900,
        "duration": "12:30",
        "date": "2026-05-01T00:00:00Z",
        "commentsCount": 2,
        "comments": [
            {"author": "u1", "text": "great", "voteCount": 5, "publishedTimeText": "1 day ago"},
            {"author": "u2", "text": "thanks", "voteCount": 0},
        ],
    }
    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", lambda actor, payload: [item])

        info = scraper.fetch_video("abc12345678", with_comments=True, comment_limit=200)
        signals = scraper.map_signals(info)
        assert signals["id"] == "abc12345678"
        assert signals["channel_id"] == "UC_chan"
        assert signals["views"] == 27000
        assert signals["likes"] == 900
        assert signals["duration_sec"] == 750
        assert signals["published_at"] is not None and signals["published_at"].year == 2026

        comments = scraper.map_comments(info, 200)
        assert len(comments) == 2
        assert comments[0]["author"] == "u1"
        assert comments[0]["likes"] == 5
    print("fetch_video_maps_into_signals: ok")


def test_scraper_falls_back_to_ytdlp_on_apify_error():
    """A raising Apify call must degrade to local yt-dlp, not crash the scrape."""
    from app.ingestion import apify, scraper

    called = {}

    def _boom(actor, payload):
        raise RuntimeError("apify down")

    def _fake_ytdlp(video_id, *, with_comments, comment_limit):
        called["hit"] = video_id
        return {"id": video_id}

    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", _boom)
        swap.attr(scraper, "_ytdlp_fetch_video", _fake_ytdlp)

        info = scraper.fetch_video("zzz11112222", with_comments=False, comment_limit=0)
        assert info == {"id": "zzz11112222"}
        assert called["hit"] == "zzz11112222"
    print("scraper_falls_back_to_ytdlp_on_apify_error: ok")


# ---- transcript mapping (multiple actor shapes) ----

def test_transcript_segment_list():
    from app.ingestion import apify

    items = [{"transcript": [
        {"text": "hello", "start": 0.0, "duration": 1.0},
        {"text": "world", "start": 1.0, "duration": 1.0},
    ]}]
    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", lambda a, p: items)
        res = apify.fetch_transcript("abc12345678")
        assert res is not None and res.provider == "apify"
        assert res.text == "hello world"
    print("transcript_segment_list: ok")


def test_transcript_real_shape():
    """The codepoetry actor shape: metadata + language + transcript_json[{start,end,text}]."""
    from app.ingestion import apify

    items = [{
        "metadata": {"id": "dQw4w9WgXcQ", "title": "x", "view_count": 100},
        "language": "en",
        "is_auto_generated": False,
        "transcript_json": [
            {"start": 1.36, "end": 3.04, "text": "hello"},
            {"start": 18.64, "end": 21.88, "text": "world"},
        ],
        "transcript_text": "hello world",
    }]
    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", lambda a, p: items)
        res = apify.fetch_transcript("dQw4w9WgXcQ")
        assert res is not None and res.provider == "apify" and res.lang == "en"
        assert res.text == "hello world"
        import json
        segs = json.loads(res.segments_json)
        # duration derived from end - start (actor gives `end`, not `duration`)
        assert abs(segs[0]["duration"] - 1.68) < 0.01
    print("transcript_real_shape: ok")


def test_video_metadata_nested():
    """map_signals works when signals live under a nested `metadata` block."""
    from app.ingestion import apify, scraper

    item = {"metadata": {
        "id": "dQw4w9WgXcQ", "channel_id": "UCx", "channel": "Rick",
        "view_count": 1779306474, "like_count": 19136745, "duration": 213,
        "upload_date": "20091025", "title": "t", "description": "d",
    }}
    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", lambda a, p: [item])
        info = scraper.fetch_video("dQw4w9WgXcQ", with_comments=False, comment_limit=0)
        sig = scraper.map_signals(info)
        assert sig["views"] == 1779306474
        assert sig["duration_sec"] == 213
        assert sig["channel_id"] == "UCx"
        assert sig["published_at"].year == 2009
    print("video_metadata_nested: ok")


def test_gating_is_independent():
    """Transcripts can use Apify even when scrape_provider stays ytdlp."""
    from app.config import get_settings
    from app.ingestion import apify

    with _Swap() as swap:
        swap.env("BRAIN_APIFY_TOKEN", "test-token")  # token only, provider stays ytdlp
        get_settings.cache_clear()
        assert apify.enabled() is False           # video stays local
        assert apify.transcripts_enabled() is True  # transcripts go via Apify
    print("gating_is_independent: ok")


def test_transcript_flat_text():
    from app.ingestion import apify

    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", lambda a, p: [{"text": "a flat transcript"}])
        res = apify.fetch_transcript("abc12345678")
        assert res is not None and res.text == "a flat transcript"
    print("transcript_flat_text: ok")


def test_transcript_empty():
    from app.ingestion import apify

    with _Swap() as swap:
        _enable_apify(swap)
        swap.attr(apify, "run_actor", lambda a, p: [])
        assert apify.fetch_transcript("abc12345678") is None
    print("transcript_empty: ok")


def test_apify_disabled_by_default():
    from app.config import get_settings
    from app.ingestion import apify

    get_settings.cache_clear()
    assert apify.enabled() is False
    print("apify_disabled_by_default: ok")


if __name__ == "__main__":
    test_to_seconds()
    test_to_upload_date()
    test_fetch_video_maps_into_signals()
    test_scraper_falls_back_to_ytdlp_on_apify_error()
    test_transcript_segment_list()
    test_transcript_real_shape()
    test_video_metadata_nested()
    test_gating_is_independent()
    test_transcript_flat_text()
    test_transcript_empty()
    test_apify_disabled_by_default()
    print("ALL APIFY TESTS PASSED")
