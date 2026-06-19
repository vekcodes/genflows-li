"""LinkedIn post scraping via Apify.

Fetches posts for a given LinkedIn source URL.
All scraping goes through Apify — there is no local fallback for LinkedIn.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import SourceKind
from . import apify


def fetch_posts(
    url: str,
    kind: SourceKind,
    *,
    limit: int,
    with_comments: bool,
    comment_limit: int,
) -> list[dict[str, Any]]:
    """Fetch posts for a LinkedIn profile or company page via Apify."""
    if not apify.enabled():
        raise RuntimeError(
            "LinkedIn scraping requires an Apify token. "
            "Set BRAIN_APIFY_TOKEN in your .env file. "
            "Sign up free at https://apify.com."
        )

    if kind == SourceKind.profile:
        return apify.fetch_profile_posts(
            url, limit=limit, with_comments=with_comments, comment_limit=comment_limit
        )
    elif kind == SourceKind.company:
        return apify.fetch_company_posts(
            url, limit=limit, with_comments=with_comments, comment_limit=comment_limit
        )
    else:
        raise ValueError(f"Unsupported source kind for scraping: {kind}")


def map_signals(post: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw post dict into LinkedInPost column values."""
    published_at = None
    raw_date = post.get("published_at")
    if raw_date:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                published_at = datetime.strptime(raw_date[:19], fmt[:len(raw_date[:19])])
                break
            except ValueError:
                continue

    return {
        "id": post["id"],
        "author_id": post.get("author_id") or "unknown",
        "author_name": post.get("author_name"),
        "text": post.get("text") or "",
        "reactions": int(post.get("reactions") or 0),
        "comments_count": int(post.get("comments_count") or 0),
        "shares": int(post.get("shares") or 0),
        "post_type": post.get("post_type") or "text",
        "published_at": published_at,
    }


def map_comments(post: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in (post.get("comments") or [])[:limit]:
        out.append({
            "author": c.get("author"),
            "text": c.get("text") or "",
            "likes": int(c.get("likes") or 0),
            "published_at": str(c.get("published_at") or ""),
        })
    return out
