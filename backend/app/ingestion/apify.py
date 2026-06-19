"""LinkedIn scraping via Apify actors.

Supports two source types:
  - Personal profiles: harvestapi/linkedin-profile-posts
  - Company pages:     harvestapi/linkedin-company-posts

Both actors return posts in a similar shape. Field mapping is tolerant (multiple
candidate keys) because different actor versions name fields differently.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("brain.apify")

_BASE = "https://api.apify.com/v2"


def enabled() -> bool:
    s = get_settings()
    return bool(s.apify_token)


def run_actor(actor_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an Apify actor synchronously and return its dataset items."""
    s = get_settings()
    url = f"{_BASE}/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {s.apify_token}"},
        json=payload,
        timeout=s.apify_timeout_sec,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("items", [])


def _first(item: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return default


def _to_datetime_str(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text if text else None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _map_post(item: dict[str, Any], source_url: str) -> dict[str, Any]:
    """Normalise one Apify LinkedIn post item into a canonical dict."""
    # Different actors expose the author under different keys.
    author_id = str(_first(
        item,
        "authorProfileId", "authorSlug", "profileId", "companyId",
        "authorId", "profileUrl", "companyUrl",
        default="",
    ) or "").split("/")[-1].split("?")[0].strip() or "unknown"

    author_name = str(_first(
        item, "authorName", "author", "name", "fullName", "companyName", default=""
    ) or "").strip()

    text = str(_first(
        item, "text", "content", "body", "postText", "description", default=""
    ) or "").strip()

    reactions = _to_int(_first(item, "numLikes", "likes", "reactions", "reactionCount", "likesCount"))
    comments_count = _to_int(_first(item, "numComments", "comments", "commentsCount", "commentCount"))
    shares = _to_int(_first(item, "numShares", "shares", "sharesCount", "reshareCount"))

    post_type = str(_first(item, "postType", "type", "contentType", default="text") or "text").lower()
    # Normalise post_type to known values.
    if post_type in ("article", "pulse"):
        post_type = "document"
    elif post_type not in ("image", "video", "document", "carousel"):
        post_type = "text"

    published_at = _to_datetime_str(_first(
        item, "postedAt", "publishedAt", "createdAt", "date", "time"
    ))

    # Post ID / URN — try several field names.
    post_id = str(_first(
        item, "id", "urn", "postUrn", "activityUrn", "entityUrn", default=""
    ) or "").strip()
    if not post_id:
        # Derive a stable ID from URL or author+timestamp.
        url_val = str(_first(item, "url", "postUrl", "link", default="") or "")
        post_id = url_val.split("activity-")[-1].split("-")[0] if "activity-" in url_val else ""
    if not post_id:
        import hashlib
        post_id = hashlib.md5(f"{author_id}:{text[:80]}".encode()).hexdigest()[:16]

    return {
        "id": post_id,
        "author_id": author_id,
        "author_name": author_name or author_id,
        "text": text,
        "reactions": reactions,
        "comments_count": comments_count,
        "shares": shares,
        "post_type": post_type,
        "published_at": published_at,
        "raw": item,
    }


def _map_comments(item: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    raw = _first(item, "comments", "commentsList", "topComments", default=[]) or []
    out: list[dict[str, Any]] = []
    for c in raw[:limit]:
        if not isinstance(c, dict):
            continue
        out.append({
            "author": str(_first(c, "authorName", "author", "name", default="") or "").strip(),
            "text": str(_first(c, "text", "comment", "content", default="") or "").strip(),
            "likes": _to_int(_first(c, "numLikes", "likes", "likeCount")),
            "published_at": _to_datetime_str(_first(c, "postedAt", "publishedAt", "date")),
        })
    return out


def fetch_profile_posts(profile_url: str, *, limit: int, with_comments: bool, comment_limit: int) -> list[dict[str, Any]]:
    """Fetch posts from a personal LinkedIn profile via Apify."""
    s = get_settings()
    payload: dict[str, Any] = {
        "profileUrls": [profile_url],
        "resultsLimit": limit,
    }
    if with_comments:
        payload["scrapeComments"] = True
        payload["maxComments"] = comment_limit

    items = run_actor(s.apify_linkedin_profile_actor, payload)
    posts = [_map_post(it, profile_url) for it in items if isinstance(it, dict)]
    if with_comments:
        for post, item in zip(posts, items):
            post["comments"] = _map_comments(item, comment_limit)
    return posts


def fetch_company_posts(company_url: str, *, limit: int, with_comments: bool, comment_limit: int) -> list[dict[str, Any]]:
    """Fetch posts from a LinkedIn company page via Apify."""
    s = get_settings()
    payload: dict[str, Any] = {
        "companyUrls": [company_url],
        "resultsLimit": limit,
    }
    if with_comments:
        payload["scrapeComments"] = True
        payload["maxComments"] = comment_limit

    items = run_actor(s.apify_linkedin_company_actor, payload)
    posts = [_map_post(it, company_url) for it in items if isinstance(it, dict)]
    if with_comments:
        for post, item in zip(posts, items):
            post["comments"] = _map_comments(item, comment_limit)
    return posts
