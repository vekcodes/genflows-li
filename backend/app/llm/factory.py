"""Resolve the configured LLM provider."""
from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .anthropic_api import AnthropicApiProvider
from .base import LLMError, LLMProvider
from .claude_cli import ClaudeCliProvider
from .retry import RetryingProvider


@lru_cache
def get_llm() -> LLMProvider | None:
    settings = get_settings()
    provider = settings.llm_provider
    inner: LLMProvider | None = None
    if provider == "claude_cli":
        inner = ClaudeCliProvider()
    elif provider == "anthropic":
        inner = AnthropicApiProvider()
    if inner is None:
        return None
    return RetryingProvider(
        inner, max_retries=settings.llm_max_retries, backoff_sec=settings.llm_retry_backoff_sec
    )


def require_llm() -> LLMProvider:
    """Return a ready provider or raise LLMError (API layer maps this to 501)."""
    llm = get_llm()
    if not llm or not llm.available():
        raise LLMError(
            "No LLM provider available. Set BRAIN_LLM_PROVIDER=claude_cli and log in to "
            "Claude Code (or use BRAIN_LLM_PROVIDER=anthropic + BRAIN_ANTHROPIC_API_KEY)."
        )
    return llm
