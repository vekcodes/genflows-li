"""Per-video signal + comment scraping via yt-dlp (single network call each).

Signals — views/likes/duration/dates/title/description — are what competitor
analysis runs on. Comments feed pain-point mining. We never download media.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from yt_dlp import YoutubeDL


def _parse_upload_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def fetch_video(video_id: str, *, with_comments: bool, comment_limit: int) -> dict[str, Any]:
    """Return raw info for a single video (metadata, +comments optional).

    Routes through Apify when configured (offloads this machine), and falls back to local
    yt-dlp on any Apify error so a misconfigured actor can never break ingestion.
    """
    from . import apify

    if apify.enabled():
        try:
            return apify.fetch_video(video_id, with_comments=with_comments, comment_limit=comment_limit)
        except Exception as exc:  # noqa: BLE001 - degrade to local scraping
            import logging

            logging.getLogger("brain.ingest").warning(
                "Apify fetch failed for %s (%s); falling back to yt-dlp", video_id, exc
            )
    return _ytdlp_fetch_video(video_id, with_comments=with_comments, comment_limit=comment_limit)


def _ytdlp_fetch_video(video_id: str, *, with_comments: bool, comment_limit: int) -> dict[str, Any]:
    """Local yt-dlp fetch (the fallback backend)."""
    opts: dict = {
        "quiet": True,
        "skip_download": True,
        "noprogress": True,
        "ignoreerrors": True,
    }
    if with_comments:
        opts["getcomments"] = True
        # Cap comment extraction — it is the slow part.
        opts["extractor_args"] = {"youtube": {"max_comments": [str(comment_limit), "all", "0"]}}

    url = f"https://www.youtube.com/watch?v={video_id}"
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise ValueError(f"Could not fetch video {video_id}")
    return info


def map_signals(info: dict[str, Any]) -> dict[str, Any]:
    """Flatten yt-dlp info into Video column values."""
    return {
        "id": info["id"],
        "channel_id": info.get("channel_id") or info.get("uploader_id") or "",
        "channel_name": info.get("channel") or info.get("uploader"),
        "title": info.get("title") or "",
        "description": info.get("description") or "",
        "views": int(info.get("view_count") or 0),
        "likes": int(info.get("like_count") or 0),
        "duration_sec": int(info.get("duration") or 0),
        "published_at": _parse_upload_date(info.get("upload_date")),
        "comment_count": int(info.get("comment_count") or 0),
    }


def map_comments(info: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in (info.get("comments") or [])[:limit]:
        out.append(
            {
                "author": c.get("author"),
                "text": c.get("text") or "",
                "likes": int(c.get("like_count") or 0),
                "published_at": str(c.get("_time_text") or c.get("timestamp") or ""),
            }
        )
    return out
