"""Politeness controls for scraping: rate limiting, retries, jittered delays.

These protect the (residential) IP from bursty traffic and ride out transient
YouTube/network errors. All timing is injectable so they're unit-testable
without real sleeping or wall-clock dependence.
"""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

from .config import get_settings

T = TypeVar("T")


class SlidingWindowLimiter:
    """Thread-safe sliding-window limiter: at most `max_events` per `window_sec`."""

    def __init__(self, max_events: int, window_sec: float, *, clock: Callable[[], float] = time.monotonic):
        self.max_events = max_events
        self.window_sec = window_sec
        self._clock = clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.window_sec:
            self._events.popleft()

    def try_acquire(self) -> bool:
        """Record one event and return True, or False if the window is full."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            if len(self._events) >= self.max_events:
                return False
            self._events.append(now)
            return True

    def remaining(self) -> int:
        with self._lock:
            self._purge(self._clock())
            return max(0, self.max_events - len(self._events))


def with_retries(
    fn: Callable[[], T],
    *,
    retries: int,
    base_delay: float,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Call fn, retrying on exception with exponential backoff + jitter."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception:
            if attempt >= retries:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt)) * (0.5 + rand())
            sleep(delay)
            attempt += 1


def jittered_delay(
    min_sec: float,
    max_sec: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[float, float], float] = random.uniform,
) -> None:
    """Sleep a random duration in [min_sec, max_sec] (no-op if max_sec <= 0)."""
    if max_sec <= 0:
        return
    sleep(rand(min_sec, max(min_sec, max_sec)))


@lru_cache
def scrape_limiter() -> SlidingWindowLimiter:
    """Process-wide hourly cap on videos scraped, from settings."""
    return SlidingWindowLimiter(get_settings().scrape_hourly_video_cap, 3600.0)
