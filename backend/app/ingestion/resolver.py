"""LinkedIn URL resolver — classify the URL and extract the source slug.

Post listing happens inside the Apify actor call. This module only classifies
the URL and extracts the identifier so the pipeline knows which actor to call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import SourceKind


@dataclass
class Resolved:
    kind: SourceKind
    external_id: str | None    # profile slug or company slug
    title: str | None
    post_ids: list[str] = field(default_factory=list)
    post_reactions: dict[str, int | None] = field(default_factory=dict)


def resolve(url: str) -> Resolved:
    """Classify a LinkedIn URL and return kind + slug.

    Supports:
      linkedin.com/in/username          → profile
      linkedin.com/company/name         → company
      linkedin.com/company/name/posts   → company
      linkedin.com/showcase/name        → company (showcase page)
    """
    clean = url.strip().rstrip("/")

    if "/in/" in clean:
        slug = clean.split("/in/")[-1].split("/")[0].split("?")[0].strip()
        if not slug:
            raise ValueError(f"Cannot extract profile slug from: {url}")
        return Resolved(kind=SourceKind.profile, external_id=slug, title=None)

    if "/company/" in clean or "/showcase/" in clean:
        key = "/company/" if "/company/" in clean else "/showcase/"
        slug = clean.split(key)[-1].split("/")[0].split("?")[0].strip()
        if not slug:
            raise ValueError(f"Cannot extract company slug from: {url}")
        return Resolved(kind=SourceKind.company, external_id=slug, title=None)

    if "/hashtag/" in clean:
        slug = clean.split("/hashtag/")[-1].split("/")[0].split("?")[0].strip().lstrip("#")
        return Resolved(kind=SourceKind.hashtag, external_id=slug, title=f"#{slug}")

    raise ValueError(
        f"Cannot classify LinkedIn URL: {url!r}. "
        "Expected linkedin.com/in/username or linkedin.com/company/name"
    )
