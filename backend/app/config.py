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
    serverless: bool = Field(default_factory=lambda: bool(os.environ.get("VERCEL")))

    # --- API auth ---
    api_key: str | None = None

    # --- LinkedIn ingestion via Apify ---
    # Apify API token (https://console.apify.com/account/integrations).
    apify_token: str | None = None
    # Actor for scraping personal LinkedIn profile posts.
    apify_linkedin_profile_actor: str = "harvestapi/linkedin-profile-posts"
    # Actor for scraping LinkedIn company page posts.
    apify_linkedin_company_actor: str = "harvestapi/linkedin-company-posts"
    # Max posts fetched per source per scrape run.
    apify_post_limit: int = 50
    # Max comments fetched per post (set 0 to skip comment scraping).
    comment_limit: int = 20
    apify_timeout_sec: int = 300

    # --- Generation novelty ---
    novelty_max_similarity: float = 0.78

    # --- Scraping politeness ---
    scrape_min_delay_sec: float = 1.0
    scrape_max_delay_sec: float = 3.0
    scrape_max_retries: int = 3
    scrape_backoff_base_sec: float = 2.0
    scrape_hourly_video_cap: int = 500    # posts per rolling hour

    # --- Scheduler ---
    scheduler_enabled: bool = False
    scheduler_interval_minutes: int = 30
    default_cadence_hours: int = 24

    # --- Agentic content engine ---
    agent_enabled: bool = False
    agent_weekly_day: int = 0
    agent_weekly_hour: int = 8
    agent_rescore_hour: int = 6
    agent_max_videos_per_source: int = 75  # posts per source
    agent_popular_per_source: int = 20
    popular_scan_cap: int = 300
    scrape_prescan_delay_sec: float = 0.5

    # --- LLM provider ---
    llm_provider: Literal["claude_cli", "anthropic", "none"] = "claude_cli"

    claude_cli_path: str = "claude"
    claude_model: str = "claude-opus-4-8"
    claude_code_oauth_token: str | None = None
    llm_timeout_sec: int = 120
    llm_max_retries: int = 2
    llm_retry_backoff_sec: float = 2.0

    anthropic_api_key: str | None = None

    # --- Virality model cache ---
    virality_cache_ttl_sec: int = 600

    # --- Brain Wiki (opt-in qualitative layer) ---
    brain_wiki_enabled: bool = False
    brain_wiki_dir: str = "brain_wiki/wiki"


@lru_cache
def get_settings() -> Settings:
    return Settings()
