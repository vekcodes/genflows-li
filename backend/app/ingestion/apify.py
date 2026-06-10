"""Hosted scraping via Apify actors — the offload backend for `scraper`/`transcripts`.

Why: yt-dlp runs on this machine (CPU + residential IP) and YouTube IP-blocks the caption
endpoint after volume. Apify runs the scrape on its infrastructure behind residential proxies,
which moves the load off the box and gets captions without the block.

Design: every function here returns data in the SHAPE the existing pipeline already consumes —
`fetch_video` returns a yt-dlp-compatible info dict (so `scraper.map_signals`/`map_comments`
work unchanged) and `fetch_transcript` returns a `TranscriptResult`. Callers try Apify first
(when enabled) and fall back to yt-dlp on any error, so a wrong actor slug or schema can never
break ingestion — it just degrades to local scraping.

Field mapping is deliberately tolerant (multiple candidate keys) because different public
YouTube actors name fields differently. Validate once against a real token; see GOING_LIVE.md.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("brain.apify")

_BASE = "https://api.apify.com/v2"


def enabled() -> bool:
    """True when video signals/comments should be fetched via Apify (needs a video actor)."""
    s = get_settings()
    return s.scrape_provider == "apify" and bool(s.apify_token) and bool(s.apify_video_actor)


def transcripts_enabled() -> bool:
    """True when transcripts should be fetched via Apify — independent of scrape_provider."""
    s = get_settings()
    return bool(s.apify_token) and bool(s.apify_transcript_actor)


# ---- low-level actor run ----

def run_actor(actor_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an actor synchronously and return its dataset items.

    Uses Apify's run-sync-get-dataset-items endpoint: one HTTP call that starts the actor,
    waits for it to finish, and returns the produced items. Raises on transport/HTTP errors
    so the caller can fall back to yt-dlp.

    The token goes in the Authorization header (not the query string) so it can't leak into
    request logs / proxy access logs.
    """
    s = get_settings()
    url = f"{_BASE}/acts/{actor_id}/run-sync-get-dataset-items"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {s.apify_token}"},
        json=payload,
        timeout=s.apify_timeout_sec,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("items", [])  # be tolerant of shape


# ---- helpers ----

def _first(item: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present, non-None value among candidate keys."""
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return default


def _to_seconds(value: Any) -> int:
    """Parse a duration that may be an int, '1:23', '1:02:03', or ISO 'PT1M23S'."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if ":" in text:  # HH:MM:SS or MM:SS
        parts = text.split(":")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return 0
        secs = 0
        for n in nums:
            secs = secs * 60 + n
        return secs
    if text.upper().startswith("PT"):  # ISO 8601 duration
        import re

        m = re.findall(r"(\d+)([HMS])", text.upper())
        unit = {"H": 3600, "M": 60, "S": 1}
        return sum(int(n) * unit[u] for n, u in m)
    try:
        return int(float(text))
    except ValueError:
        return 0


def _to_upload_date(value: Any) -> str | None:
    """Normalise an ISO/date string into yt-dlp's 'YYYYMMDD' (what map_signals parses)."""
    if not value:
        return None
    text = str(value)
    # Take the leading date portion of an ISO timestamp and strip separators.
    date_part = text.split("T")[0].replace("-", "").replace("/", "")
    return date_part[:8] if len(date_part) >= 8 and date_part[:8].isdigit() else None


def _map_comments(item: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Map an actor's comments into yt-dlp's `comments` entry shape (for map_comments)."""
    raw = _first(item, "comments", "commentsList", default=[]) or []
    out: list[dict[str, Any]] = []
    for c in raw[:limit]:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "author": _first(c, "author", "authorName", "name"),
                "text": _first(c, "text", "comment", "content", default="") or "",
                "like_count": int(_first(c, "voteCount", "likes", "likeCount", default=0) or 0),
                "timestamp": _first(c, "publishedTimeText", "publishedAt", "date", default=""),
            }
        )
    return out


def _to_ytdlp_info(item: dict[str, Any], *, with_comments: bool, comment_limit: int) -> dict[str, Any]:
    """Translate one Apify video item into a yt-dlp-compatible info dict.

    Some actors put the video signals under a nested `metadata` object (e.g. the transcript
    actor) — merge that in so the same mapper works for both flat and nested shapes.
    """
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    src = {**meta, **{k: v for k, v in item.items() if k != "metadata"}}  # top-level wins

    info: dict[str, Any] = {
        "id": _first(src, "id", "videoId", "video_id", default=""),
        "channel_id": _first(src, "channelId", "channel_id", default=""),
        "channel": _first(src, "channelName", "channel", "author"),
        "uploader": _first(src, "channelName", "channel", "author"),
        "uploader_id": _first(src, "channelId", "channel_id"),
        "title": _first(src, "title", default="") or "",
        "description": _first(src, "text", "description", default="") or "",
        "view_count": int(_first(src, "viewCount", "views", "view_count", default=0) or 0),
        "like_count": int(_first(src, "likes", "likeCount", "like_count", default=0) or 0),
        "duration": _to_seconds(_first(src, "duration", "durationSeconds", "lengthSeconds")),
        "upload_date": _to_upload_date(_first(src, "date", "uploadDate", "upload_date", "publishedAt", "uploadedAt")),
        "comment_count": int(_first(src, "commentsCount", "commentCount", "comment_count", default=0) or 0),
    }
    if with_comments:
        info["comments"] = _map_comments(src, comment_limit)
    return info


# ---- public API (mirrors scraper / transcripts) ----

def fetch_video(video_id: str, *, with_comments: bool, comment_limit: int) -> dict[str, Any]:
    """Fetch one video's signals (+comments) via Apify, shaped like yt-dlp's info dict."""
    s = get_settings()
    payload: dict[str, Any] = {
        "startUrls": [{"url": f"https://www.youtube.com/watch?v={video_id}"}],
        "maxResults": 1,
        "maxResultsShorts": 0,
        "downloadSubtitles": False,
    }
    if with_comments:
        payload["scrapeComments"] = True
        payload["maxComments"] = comment_limit
    items = run_actor(s.apify_video_actor, payload)
    if not items:
        raise ValueError(f"Apify returned no items for video {video_id}")
    return _to_ytdlp_info(items[0], with_comments=with_comments, comment_limit=comment_limit)


def _seg_duration(seg: dict[str, Any]) -> float:
    """Segment duration: prefer an explicit duration, else end - start (the actor uses `end`)."""
    dur = _first(seg, "duration", "dur")
    if dur is not None:
        return float(dur)
    start = float(_first(seg, "start", "offset", "startTime", default=0) or 0)
    end = _first(seg, "end", "endTime")
    return round(float(end) - start, 3) if end is not None else 0.0


def fetch_transcript(video_id: str):
    """Fetch a transcript via Apify. Returns a `TranscriptResult` or None.

    Validated against codepoetry/youtube-transcript-ai-scraper, whose item shape is:
      { metadata:{...}, language, transcript_json:[{start,end,text}], transcript_text }
    Also handles a few other common actor shapes (flat segment lists / 'transcript' key).
    """
    import json

    from .transcripts import TranscriptResult

    s = get_settings()
    payload: dict[str, Any] = {
        "startUrls": [{"url": f"https://www.youtube.com/watch?v={video_id}"}],
        "maxResults": 1,
        "languages": [x.strip() for x in s.apify_transcript_languages.split(",") if x.strip()],
        "outputFormats": ["json", "text"],
        "enableAiFallback": s.apify_enable_ai_fallback,
    }
    items = run_actor(s.apify_transcript_actor, payload)
    if not items:
        return None

    item = items[0]
    lang = _first(item, "language", "lang")
    segments = _first(item, "transcript_json", "transcript", "captions", "segments")
    if segments is None and len(items) > 1 and all(
        isinstance(i, dict) and "text" in i for i in items
    ):
        segments = items  # the dataset items themselves ARE the segments

    if isinstance(segments, list) and segments:
        segs = [
            {
                "text": _first(seg, "text", default="") or "",
                "start": float(_first(seg, "start", "offset", "startTime", default=0) or 0),
                "duration": _seg_duration(seg),
            }
            for seg in segments
            if isinstance(seg, dict)
        ]
        text = " ".join(s_["text"] for s_ in segs).strip()
        if text:
            return TranscriptResult(
                lang=lang, provider="apify", text=text,
                segments_json=json.dumps(segs, ensure_ascii=False),
            )

    flat = _first(item, "transcript_text", "text", "transcriptText", default="")
    if isinstance(flat, str) and flat.strip():
        return TranscriptResult(
            lang=lang, provider="apify", text=flat.strip(),
            segments_json=json.dumps([{"text": flat.strip(), "start": 0, "duration": 0}]),
        )
    return None
