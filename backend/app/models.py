"""Raw Lake schema (Layer C) + sources registry (Layer A).

LinkedIn edition: tracks profiles/companies as sources, and their posts + comments.
Everything downstream (baselines, outliers, insights) is derived from and
re-derivable from these tables, so they stay deliberately raw/append-only.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.utcnow()


class SourceKind(str, Enum):
    profile = "profile"    # personal LinkedIn profile
    company = "company"    # LinkedIn company page
    hashtag = "hashtag"    # LinkedIn hashtag feed


class IngestStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


# ---- Layer A: Sources registry / watchlist ----
class Source(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True)
    kind: SourceKind
    external_id: Optional[str] = Field(default=None, index=True)  # LinkedIn username/company slug
    title: Optional[str] = None
    niche: Optional[str] = Field(default=None, index=True)
    cadence_hours: int = 24
    active: bool = True
    last_scraped_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


# ---- Layer C: Raw LinkedIn post signals ----
class LinkedInPost(SQLModel, table=True):
    # LinkedIn post URN is the natural primary key.
    id: str = Field(primary_key=True)
    source_id: Optional[int] = Field(default=None, foreign_key="source.id", index=True)
    author_id: str = Field(index=True)    # profile slug or company slug
    author_name: Optional[str] = None
    text: str = ""
    reactions: int = 0
    comments_count: int = 0
    shares: int = 0
    post_type: str = "text"  # text | image | video | document | carousel
    published_at: Optional[datetime] = Field(default=None, index=True)
    ingested_at: datetime = Field(default_factory=utcnow)


class PostComment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: str = Field(foreign_key="linkedinpost.id", index=True)
    author: Optional[str] = None
    text: str = ""
    likes: int = 0
    published_at: Optional[str] = None


class IngestRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    kind: str = "scrape"
    status: IngestStatus = IngestStatus.queued
    new_videos: int = 0      # kept as new_videos for API/schema compatibility (= new posts)
    scrape_total: int = 0
    scrape_done: int = 0
    message: Optional[str] = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


# ---- Layer E: mined insights (reusable Brain state, written by the LLM) ----
class PainPoint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    niche: Optional[str] = Field(default=None, index=True)
    question: str = ""
    frequency: int = 0
    example: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class FormatPattern(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    niche: Optional[str] = Field(default=None, index=True)
    label: str = ""
    description: str = ""
    avg_multiplier: float = 0.0
    example_video_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))  # post IDs
    created_at: datetime = Field(default_factory=utcnow)


class StyleCard(SQLModel, table=True):
    channel_id: str = Field(primary_key=True)    # stores author_id for compatibility
    channel_name: Optional[str] = None
    tone: str = ""
    pacing: str = ""                             # posting frequency / rhythm
    hooks: list[str] = Field(default_factory=list, sa_column=Column(JSON))     # opening hooks used
    vocabulary: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


# ---- Layer G: Agentic content engine — durable queue / content calendar ----
class ContentStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    declined = "declined"
    scheduled = "scheduled"
    published = "published"
    scored = "scored"
    archived = "archived"


class ContentItem(SQLModel, table=True):
    """One generated LinkedIn post package on the calendar."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True)
    status: ContentStatus = Field(default=ContentStatus.proposed, index=True)

    # The deliverable.
    title: str = ""                  # hook / opening line of the post
    angle: str = ""
    format: str = "other"
    script_markdown: str = ""        # full LinkedIn post text (kept as script_markdown for compat)
    description: str = ""            # first-comment CTA text
    thumbnail_prompt: str = ""       # image/visual prompt for image posts
    evidence: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    sections: list = Field(default_factory=list, sa_column=Column(JSON))

    predicted_score: Optional[float] = None
    predicted_viral: Optional[bool] = None
    nearest_analogs: list = Field(default_factory=list, sa_column=Column(JSON))

    channel_id: Optional[str] = None          # author_id
    niche: Optional[str] = Field(default=None, index=True)
    scheduled_for: Optional[date] = None

    declined_reason: Optional[str] = None
    regenerated_from_id: Optional[int] = Field(default=None, foreign_key="contentitem.id")

    published_video_id: Optional[str] = None   # post URN after publishing
    published_url: Optional[str] = None
    published_at: Optional[datetime] = None
    actual_multiplier: Optional[float] = None
    performed: Optional[bool] = None
    reward: Optional[float] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ContentRun(SQLModel, table=True):
    """Durable progress for one batch generation."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True)
    status: IngestStatus = IngestStatus.running
    phase: str = "queued"
    scrape_total: int = 0
    scrape_done: int = 0
    n_requested: int = 0
    n_done: int = 0
    message: Optional[str] = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class FeedbackKind(str, Enum):
    decline = "decline"
    approve = "approve"
    performance = "performance"


class ContentFeedback(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: Optional[int] = Field(default=None, foreign_key="contentitem.id", index=True)
    kind: FeedbackKind
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class CreatorProfile(SQLModel, table=True):
    """Saved settings the weekly agent uses."""
    id: Optional[int] = Field(default=1, primary_key=True)
    offer: str = ""
    niche: Optional[str] = None
    n_per_week: int = 3
    target_score: float = 60.0
    duration_sec: int = 600    # kept for API compat; not meaningful for LinkedIn
    updated_at: datetime = Field(default_factory=utcnow)
