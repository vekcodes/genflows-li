"""URL resolver — video vs channel/playlist, and the list of video ids.

Uses yt-dlp's flat extraction so listing a channel is cheap (ids only, no
per-video network calls). The pipeline then fetches full signals only for
videos it hasn't seen — that's what makes ingestion incremental.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from yt_dlp import YoutubeDL

from ..models import SourceKind

_CHANNEL_HINTS = ("/channel/", "/@", "/c/", "/user/")


@dataclass
class Resolved:
    kind: SourceKind
    external_id: str | None
    title: str | None
    video_ids: list[str] = field(default_factory=list)  # channel order (recent-first)
    # id -> view_count when the flat listing exposes it (used to pick popular videos).
    video_views: dict[str, int | None] = field(default_factory=dict)


def _channel_videos_url(url: str) -> str:
    """Point channel URLs at their /videos tab so we list uploads, not tabs."""
    if any(h in url for h in _CHANNEL_HINTS) and not url.rstrip("/").endswith(
        ("/videos", "/streams", "/shorts")
    ):
        return url.rstrip("/") + "/videos"
    return url


def resolve(url: str, limit: int | None = None) -> Resolved:
    is_channelish = any(h in url for h in _CHANNEL_HINTS) or "list=" in url
    target = _channel_videos_url(url) if is_channelish else url

    opts: dict = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noprogress": True,
        "ignoreerrors": True,
    }
    if limit:
        opts["playlistend"] = limit

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)

    if info is None:
        raise ValueError(f"Could not resolve URL: {url}")

    # A single video has no 'entries'.
    if info.get("_type") not in ("playlist", "multi_video") and "entries" not in info:
        return Resolved(
            kind=SourceKind.video,
            external_id=info.get("id"),
            title=info.get("title"),
            video_ids=[info["id"]] if info.get("id") else [],
        )

    entries = [e for e in (info.get("entries") or []) if e]
    yt = [e for e in entries if e.get("id") and e.get("ie_key", "Youtube") == "Youtube"]
    video_ids = [e["id"] for e in yt]
    # Flat channel listings often expose view_count per entry — keep it so the pipeline
    # can add the channel's most-popular videos on top of the most-recent ones.
    video_views = {e["id"]: e.get("view_count") for e in yt}

    kind = SourceKind.playlist if "list=" in url else SourceKind.channel
    return Resolved(
        kind=kind,
        external_id=info.get("channel_id") or info.get("id"),
        title=info.get("channel") or info.get("title"),
        video_ids=video_ids,
        video_views=video_views,
    )
