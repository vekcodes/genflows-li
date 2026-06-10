"""Coax JSON out of an LLM text response, robustly."""
from __future__ import annotations

import json
import re
from typing import Any

from .base import LLMProvider


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating code fences / surrounding prose."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fall back to the outermost array or object in the text.
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError("No JSON found in LLM output")


def complete_json(llm: LLMProvider, prompt: str, *, system: str | None = None) -> Any:
    try:
        return extract_json(llm.complete(prompt, system=system))
    except ValueError:
        # One corrective retry: the model produced prose instead of JSON.
        nudged = (
            prompt
            + "\n\nIMPORTANT: your previous reply was not parseable JSON. "
            "Respond with ONLY the valid JSON — no prose, no code fences, no preamble."
        )
        return extract_json(llm.complete(nudged, system=system))
