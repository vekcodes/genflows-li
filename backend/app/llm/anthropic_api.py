"""Fallback provider: Anthropic API with an API key (pay-per-token).

Useful for CI or when the Claude CLI isn't available. Set BRAIN_LLM_PROVIDER=anthropic
and BRAIN_ANTHROPIC_API_KEY.
"""
from __future__ import annotations

from ..config import get_settings
from .base import LLMError


class AnthropicApiProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self._s = get_settings()

    def available(self) -> bool:
        return bool(self._s.anthropic_api_key)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self.available():
            raise LLMError("BRAIN_ANTHROPIC_API_KEY is not set.")
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("`anthropic` package not installed.") from exc

        client = anthropic.Anthropic(api_key=self._s.anthropic_api_key)
        msg = client.messages.create(
            model=self._s.claude_model,
            # Full polished scripts can exceed 2048 tokens; don't truncate them.
            max_tokens=8192,
            system=system or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if block.type == "text")
