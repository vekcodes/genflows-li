"""Layer 3 / FR-4.7: market-demand validation (external, free).

Google Trends (via pytrends) for interest direction + YouTube search-suggest for the
exact phrases people search. Both hit the network and can be flaky/blocked, so every
call degrades gracefully to `available: false` instead of raising.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("brain.demand")


def trend_direction(values: list[float]) -> str:
    """Rising / flat / falling by comparing the first vs last third of the series."""
    if len(values) < 2:
        return "flat"
    third = max(1, len(values) // 3)
    first = sum(values[:third]) / third
    last = sum(values[-third:]) / third
    if last > first * 1.15:
        return "rising"
    if last < first * 0.85:
        return "falling"
    return "flat"


def parse_suggest(payload: Any) -> list[str]:
    """Parse the autocomplete response shape: [query, [suggestions], ...]."""
    if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list):
        return [str(s) for s in payload[1] if isinstance(s, str)]
    return []


def search_suggest(query: str, *, timeout: float = 10.0) -> list[str]:
    """Free Google autocomplete suggestions for a query (for LinkedIn topic research)."""
    params = {"client": "firefox", "q": query + " linkedin", "hl": "en"}
    try:
        r = httpx.get("https://suggestqueries.google.com/complete/search", params=params, timeout=timeout)
        r.raise_for_status()
        results = parse_suggest(r.json())
        # Strip " linkedin" suffix that we added for better results.
        return [s.replace(" linkedin", "").strip() for s in results]
    except Exception as exc:
        log.warning("search_suggest failed for %r: %s", query, exc)
        return []


def google_trends(keyword: str, *, timeframe: str = "today 12-m", geo: str = "") -> dict:
    try:
        from pytrends.request import TrendReq

        py = TrendReq(hl="en-US")
        py.build_payload([keyword], timeframe=timeframe, geo=geo)
        df = py.interest_over_time()
        if df is None or df.empty or keyword not in df:
            return {"available": False, "reason": "no data"}
        series = [float(x) for x in df[keyword].tolist()]
        return {
            "available": True,
            "interest": int(series[-1]),
            "direction": trend_direction(series),
            "history": [int(x) for x in series],
        }
    except Exception as exc:
        log.warning("google_trends failed for %r: %s", keyword, exc)
        return {"available": False, "reason": str(exc)}


def validate_demand(keyword: str) -> dict:
    return {
        "keyword": keyword,
        "trends": google_trends(keyword),
        "suggestions": search_suggest(keyword),
    }

