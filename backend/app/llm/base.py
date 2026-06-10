"""LLM provider interface. Swap implementations without touching call sites."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def available(self) -> bool:
        """Cheap check that this provider can actually run (auth/binary present)."""
        ...

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        """One-shot prompt -> text completion."""
        ...
