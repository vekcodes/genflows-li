"""Transparent retry wrapper for any LLM provider.

Transient failures (CLI timeout, API hiccup, non-zero exit) get exponential-backoff retries;
configuration problems (provider unavailable) fail immediately with the provider's own message.
"""
from __future__ import annotations

import logging
import time

from .base import LLMError, LLMProvider

log = logging.getLogger("brain.llm")


class RetryingProvider:
    def __init__(self, inner: LLMProvider, *, max_retries: int, backoff_sec: float) -> None:
        self.inner = inner
        self.name = inner.name
        self._max_retries = max(0, max_retries)
        self._backoff = backoff_sec

    def available(self) -> bool:
        return self.inner.available()

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self.inner.available():
            # Config problem (no binary / no key) — retrying can't fix it; let the inner
            # provider raise its descriptive LLMError.
            return self.inner.complete(prompt, system=system)

        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self.inner.complete(prompt, system=system)
            except Exception as exc:  # noqa: BLE001 - anything transient is worth one more try
                last = exc
                if attempt < self._max_retries:
                    delay = self._backoff * (2**attempt)
                    log.warning(
                        "LLM call failed (%s); retry %s/%s in %.1fs",
                        exc, attempt + 1, self._max_retries, delay,
                    )
                    time.sleep(delay)
        if isinstance(last, LLMError):
            raise last
        raise LLMError(f"{type(last).__name__}: {last}") from last
