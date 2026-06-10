"""Runtime configuration (env-driven). See .env.example."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRAIN_", extra="ignore")

    # --- Storage ---
    database_url: str = "sqlite:///./brain.db"

    # --- Serverless mode (Vercel) ---
    # No background threads / scheduler: long work runs synchronously inside the request
    # (bounded by the platform's maxDuration) and periodic jobs run via the /cron endpoints
    # hit by Vercel Cron. Auto-detected on Vercel; override with BRAIN_SERVERLESS.
    serverless: bool = Field(default_factory=lambda: bool(os.environ.get("VERCEL")))

    # --- API auth ---
    # If set, all non-public endpoints require header `X-API-Key: <this>`.
    # Leave empty for local dev (open API).
    api_key: str | None = None

    # --- Ingestion ---
    # Scraping has two backends, gated INDEPENDENTLY:
    #
    #  • Video signals + comments — `scrape_provider`:
    #      ytdlp -> local yt-dlp (free; metadata isn't IP-blocked, and it returns comments)
    #      apify -> a hosted video actor (offloads the machine; needs apify_video_actor).
    #    Falls back to yt-dlp automatically on any Apify error.
    #  • Transcripts — used automatically whenever apify_token + apify_transcript_actor are set,
    #    REGARDLESS of scrape_provider. Apify's residential proxies bypass the caption IP-block,
    #    so this is the recommended transcript path (retires local Whisper). Falls back to the
    #    local caption API / Whisper on any Apify error.
    scrape_provider: Literal["ytdlp", "apify"] = "ytdlp"
    # Apify API token (https://console.apify.com/account/integrations).
    apify_token: str | None = None
    # Actor IDs (username~actor-name or the bare actor id). The mapping in ingestion/apify.py is
    # defensive (multi-key + handles a nested `metadata` block); validated against the default
    # transcript actor (see GOING_LIVE.md). The video actor default is a placeholder — set your
    # own before flipping scrape_provider=apify.
    apify_video_actor: str = "streamers~youtube-scraper"
    apify_transcript_actor: str = "codepoetry~youtube-transcript-ai-scraper"
    apify_transcript_languages: str = "en"   # comma-separated, passed as the actor's `languages`
    # The transcript actor can fall back to paid AI transcription when no captions exist. Off by
    # default to control cost; on = closest to "always get a transcript".
    apify_enable_ai_fallback: bool = False
    apify_timeout_sec: int = 300
    # Cap comments fetched per video (yt-dlp comment scraping is slow/heavy).
    comment_limit: int = 200
    # Skip downloading media; we only need metadata + transcripts + comments.
    request_timeout_sec: int = 60
    # Optional proxy for transcript fetching (e.g. http://user:pass@host:port). YouTube
    # IP-blocks the caption endpoint after volume; a clean-IP proxy is the documented fix.
    # Used for BOTH the caption API and the Whisper audio download. Empty = direct.
    transcript_proxy: str | None = None
    # Local Whisper fallback: when captions are blocked/unavailable, download the audio (a
    # different, un-blocked endpoint) and transcribe it on-device with faster-whisper. Free
    # and block-proof, but CPU-heavy. Opt-in.
    transcript_whisper_enabled: bool = False
    whisper_model: str = "tiny.en"   # tiny.en (fast) … base.en/small.en (better, slower)
    whisper_compute_type: str = "int8"  # int8 = fast on CPU
    whisper_max_duration_sec: int = 3600  # skip videos longer than this (bounds CPU per item)
    # Auto-backfill missing transcripts on each scheduler tick (captions first, Whisper fallback),
    # bounded so it never hogs the CPU — drains the backlog + covers new videos over time.
    transcript_autofill_enabled: bool = True
    transcript_autofill_per_tick: int = 8
    transcript_autofill_interval_minutes: int = 10

    # --- Generation novelty ---
    # A generated title is rejected as a near-copy when its similarity to an existing video /
    # queued title exceeds this (0..1). The virality model still ranks what survives, so output
    # must be BOTH novel and high-scoring. Lower = stricter (more original). 1.0 disables it.
    novelty_max_similarity: float = 0.78

    # --- Scraping politeness (protects the residential IP) ---
    # Random pause between videos. Set both to 0 for fast local testing.
    scrape_min_delay_sec: float = 2.0
    scrape_max_delay_sec: float = 5.0
    # Retry transient fetch errors with exponential backoff + jitter.
    scrape_max_retries: int = 3
    scrape_backoff_base_sec: float = 2.0
    # Hard ceiling on videos scraped per rolling hour (across all sources).
    scrape_hourly_video_cap: int = 300

    # --- Brain Wiki (LLM-maintained qualitative knowledge layer, opt-in) ---
    # When on, ingest folds each new video into a compounding markdown wiki
    # (backend/brain_wiki/) in addition to the existing DB insight tables (dual-write).
    # Numbers always come from the DB / virality model; the wiki only explains *why*.
    brain_wiki_enabled: bool = False
    brain_wiki_dir: str = "brain_wiki/wiki"

    # --- Scheduler (continuous, incremental re-check) ---
    scheduler_enabled: bool = False  # opt-in; run workers explicitly in dev
    scheduler_interval_minutes: int = 30
    default_cadence_hours: int = 24

    # --- Agentic content engine (weekly auto-creator) ---
    # When on (and the scheduler is enabled), a weekly cron generates a content batch into the
    # queue and a daily job re-measures published items. Per-run knobs live in CreatorProfile.
    agent_enabled: bool = False
    agent_weekly_day: int = 0   # 0=Mon … 6=Sun
    agent_weekly_hour: int = 8  # local hour to run the weekly batch
    agent_rescore_hour: int = 6  # daily hour to re-measure published items
    # Per channel we full-scrape the N most-recent videos PLUS the top-K most-popular ones.
    # YouTube hides view counts in the fast listing, so popularity is found via a lightweight
    # metadata pre-scan (views only, no comments) over the back-catalogue (bounded by
    # popular_scan_cap). Incremental runs after this only fetch genuinely new videos.
    agent_max_videos_per_source: int = 75
    agent_popular_per_source: int = 20
    popular_scan_cap: int = 300          # max older videos to metadata-scan for popularity
    scrape_prescan_delay_sec: float = 0.5  # light pause between metadata-only pre-scan calls

    # --- LLM provider (the reasoning engine) ---
    # claude_cli  -> shells out to the Claude Code CLI (subscription/OAuth, no API billing)
    # anthropic   -> Anthropic API with an API key (pay-per-token fallback)
    # none        -> mining endpoints return 501 until a provider is configured
    llm_provider: Literal["claude_cli", "anthropic", "none"] = "claude_cli"

    # claude_cli provider
    claude_cli_path: str = "claude"
    claude_model: str = "claude-opus-4-8"
    # If set, exported as CLAUDE_CODE_OAUTH_TOKEN for headless CLI auth
    # (generate with `claude setup-token`). If unset, the CLI uses its own login.
    claude_code_oauth_token: str | None = None
    llm_timeout_sec: int = 120
    # Transient LLM failures (timeout, API hiccup, non-zero CLI exit) are retried with
    # exponential backoff before the content item is failed. 0 disables retries.
    llm_max_retries: int = 2
    llm_retry_backoff_sec: float = 2.0

    # anthropic provider (fallback)
    anthropic_api_key: str | None = None

    # --- Virality model cache ---
    # score() fits on full history; cache the fitted model + backtest and reuse them while the
    # video set is unchanged and the entry is younger than this TTL (a refine loop scores
    # dozens of candidates per batch — refitting each time is pure waste).
    virality_cache_ttl_sec: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
