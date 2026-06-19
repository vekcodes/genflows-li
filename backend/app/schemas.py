"""API request/response shapes (kept separate from DB models)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from .models import ContentStatus, SourceKind


class SourceCreate(BaseModel):
    url: str
    niche: str | None = None
    cadence_hours: int = 24


class SourceRead(BaseModel):
    id: int
    url: str
    kind: SourceKind
    external_id: str | None
    title: str | None
    niche: str | None
    cadence_hours: int
    active: bool
    last_scraped_at: datetime | None
    created_at: datetime


class IngestRunRead(BaseModel):
    id: int
    source_id: int
    status: str
    new_videos: int
    scrape_total: int
    scrape_done: int
    message: str | None
    started_at: datetime
    finished_at: datetime | None


class ScrapeJobRead(BaseModel):
    id: int
    source_id: int
    source_title: str | None
    source_url: str | None
    status: str
    scrape_total: int
    scrape_done: int
    new_videos: int
    message: str | None
    started_at: datetime
    finished_at: datetime | None


class BaselineRead(BaseModel):
    channel_id: str       # author_id
    channel_name: str | None
    video_count: int      # post count
    median_views: float   # median reactions


class OutlierRead(BaseModel):
    video_id: str         # post_id
    title: str            # post text excerpt
    channel_id: str       # author_id
    views: int            # reactions
    channel_median: float
    multiplier: float


class LLMStatus(BaseModel):
    provider: str | None
    available: bool


# ---- Agentic content engine ----

class ContentItemRead(BaseModel):
    id: int
    batch_id: str
    status: ContentStatus
    title: str
    angle: str
    format: str
    script_markdown: str
    description: str
    thumbnail_prompt: str
    evidence: list[str]
    sections: list
    predicted_score: float | None
    predicted_viral: bool | None
    nearest_analogs: list
    channel_id: str | None
    niche: str | None
    scheduled_for: date | None
    declined_reason: str | None
    regenerated_from_id: int | None
    published_video_id: str | None
    published_url: str | None
    published_at: datetime | None
    actual_multiplier: float | None
    performed: bool | None
    reward: float | None
    created_at: datetime
    updated_at: datetime


class ContentRunRead(BaseModel):
    id: int
    batch_id: str
    status: str
    phase: str
    scrape_total: int
    scrape_done: int
    n_requested: int
    n_done: int
    message: str | None
    started_at: datetime
    finished_at: datetime | None


class DeclineRequest(BaseModel):
    reason: str


class ScheduleRequest(BaseModel):
    when: date


class PublishRequest(BaseModel):
    url: str


class CreatorProfileRead(BaseModel):
    id: int
    offer: str
    niche: str | None
    n_per_week: int
    target_score: float
    duration_sec: int
    updated_at: datetime


class CreatorProfileUpdate(BaseModel):
    offer: str | None = None
    niche: str | None = None
    n_per_week: int | None = None
    target_score: float | None = None
    duration_sec: int | None = None
