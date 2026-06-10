"""Raw Lake schema (Layer C) + sources registry (Layer A).

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
    channel = "channel"
    playlist = "playlist"
    video = "video"


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
    # Resolved YouTube id (channel id / playlist id / video id).
    external_id: Optional[str] = Field(default=None, index=True)
    title: Optional[str] = None
    niche: Optional[str] = Field(default=None, index=True)
    cadence_hours: int = 24
    active: bool = True
    last_scraped_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


# ---- Layer C: Raw video signals (what analysis actually runs on) ----
class Video(SQLModel, table=True):
    # YouTube video id is the natural primary key.
    id: str = Field(primary_key=True)
    source_id: Optional[int] = Field(default=None, foreign_key="source.id", index=True)
    channel_id: str = Field(index=True)
    channel_name: Optional[str] = None
    title: str = ""
    description: str = ""
    views: int = 0
    likes: int = 0
    duration_sec: int = 0
    published_at: Optional[datetime] = Field(default=None, index=True)
    comment_count: int = 0
    has_transcript: bool = False
    ingested_at: datetime = Field(default_factory=utcnow)


class Transcript(SQLModel, table=True):
    video_id: str = Field(primary_key=True, foreign_key="video.id")
    lang: Optional[str] = None
    # 'api' (youtube-transcript-api) or 'whisper' (faster-whisper fallback).
    provider: str = "api"
    text: str = ""
    # JSON array of {start, duration, text} segments (timestamps kept).
    segments_json: str = "[]"
    fetched_at: datetime = Field(default_factory=utcnow)


class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True)
    author: Optional[str] = None
    text: str = ""
    likes: int = 0
    published_at: Optional[str] = None  # yt-dlp returns relative/text dates


class IngestRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    kind: str = "scrape"  # "scrape" | "transcripts" — so restart-recovery handles each correctly
    status: IngestStatus = IngestStatus.queued
    new_videos: int = 0
    scrape_total: int = 0   # videos this run will scrape (for the progress bar)
    scrape_done: int = 0    # videos scraped so far
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
    example_video_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class StyleCard(SQLModel, table=True):
    channel_id: str = Field(primary_key=True)
    channel_name: Optional[str] = None
    tone: str = ""
    pacing: str = ""
    hooks: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    vocabulary: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


# ---- Layer D: transcript chunks for the local vector index ----
class Chunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: str = Field(foreign_key="video.id", index=True)
    idx: int = 0
    text: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ---- Layer G: Agentic content engine — durable queue / content calendar ----
class ContentStatus(str, Enum):
    proposed = "proposed"      # freshly generated, awaiting review
    approved = "approved"      # accepted, ready to schedule/produce
    declined = "declined"      # rejected with a reason; usually spawns a replacement
    scheduled = "scheduled"    # has a calendar slot
    published = "published"    # the real video is live (URL attached); awaiting measurement
    scored = "scored"          # actual performance measured → reward computed
    archived = "archived"


class ContentItem(SQLModel, table=True):
    """One generated content package on the calendar (idea → script → thumbnail prompt)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True)
    status: ContentStatus = Field(default=ContentStatus.proposed, index=True)

    # The deliverable.
    title: str = ""
    angle: str = ""
    format: str = "other"
    script_markdown: str = ""
    description: str = ""           # YouTube description + booking CTA
    thumbnail_prompt: str = ""
    evidence: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    sections: list = Field(default_factory=list, sa_column=Column(JSON))

    # Predicted virality (from the backtested model — the gate).
    predicted_score: Optional[float] = None
    predicted_viral: Optional[bool] = None
    nearest_analogs: list = Field(default_factory=list, sa_column=Column(JSON))

    channel_id: Optional[str] = None
    niche: Optional[str] = Field(default=None, index=True)
    scheduled_for: Optional[date] = None

    # Review lineage.
    declined_reason: Optional[str] = None
    regenerated_from_id: Optional[int] = Field(default=None, foreign_key="contentitem.id")

    # Published-performance reward signal (the "RL").
    published_video_id: Optional[str] = None
    published_url: Optional[str] = None
    published_at: Optional[datetime] = None
    actual_multiplier: Optional[float] = None
    performed: Optional[bool] = None
    reward: Optional[float] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ContentRun(SQLModel, table=True):
    """Durable progress for one batch generation (mirrors IngestRun)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True)
    status: IngestStatus = IngestStatus.running
    phase: str = "queued"          # queued | scraping | mining | writing | done
    scrape_total: int = 0          # videos to scrape this run (current channel)
    scrape_done: int = 0           # videos scraped so far
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
    """Append-only learning corpus — what gets declined and how published items performed.

    Fed back into generation context so Claude adapts (the Claude-driven 'RL' memory).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: Optional[int] = Field(default=None, foreign_key="contentitem.id", index=True)
    kind: FeedbackKind
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class CreatorProfile(SQLModel, table=True):
    """Saved Settings the weekly agent uses — replaces the per-run sidebar inputs."""
    id: Optional[int] = Field(default=1, primary_key=True)
    offer: str = ""               # booking CTA woven into descriptions
    niche: Optional[str] = None
    n_per_week: int = 3
    target_score: float = 60.0
    duration_sec: int = 600
    updated_at: datetime = Field(default_factory=utcnow)
