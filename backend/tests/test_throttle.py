"""Scraping politeness controls — rate limiter, retries, jittered delay.

All timing is injected (fake clock / recorded sleeps), so these run instantly
and don't touch the network or the wall clock.

Run:  PYTHONPATH=. .venv/Scripts/python.exe tests/test_throttle.py
"""
from __future__ import annotations

import os

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


def test_sliding_window_limiter():
    from app.throttle import SlidingWindowLimiter

    t = {"now": 0.0}
    lim = SlidingWindowLimiter(max_events=3, window_sec=10.0, clock=lambda: t["now"])

    assert lim.try_acquire() is True   # 1
    assert lim.try_acquire() is True   # 2
    assert lim.try_acquire() is True   # 3
    assert lim.remaining() == 0
    assert lim.try_acquire() is False  # window full

    t["now"] = 11.0                    # slide past the window
    assert lim.remaining() == 3
    assert lim.try_acquire() is True
    print("limiter: ok")


def test_with_retries_succeeds_after_failures():
    from app.throttle import with_retries

    calls = {"n": 0}
    slept: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    out = with_retries(flaky, retries=5, base_delay=2.0, sleep=slept.append, rand=lambda: 0.5)
    assert out == "ok" and calls["n"] == 3, (out, calls)
    # Two backoff sleeps, increasing (exponential * jitter).
    assert len(slept) == 2 and slept[1] > slept[0], slept
    print("with_retries (recover): ok", slept)


def test_with_retries_gives_up():
    from app.throttle import with_retries

    slept: list[float] = []

    def always_fail():
        raise ValueError("nope")

    try:
        with_retries(always_fail, retries=2, base_delay=1.0, sleep=slept.append, rand=lambda: 0.5)
        assert False, "should have raised"
    except ValueError:
        pass
    assert len(slept) == 2, slept  # retries=2 -> 2 sleeps then raise
    print("with_retries (give up): ok")


def test_jittered_delay_noop_when_zero():
    from app.throttle import jittered_delay

    slept: list[float] = []
    jittered_delay(0.0, 0.0, sleep=slept.append)
    assert slept == [], slept

    jittered_delay(1.0, 3.0, sleep=slept.append, rand=lambda a, b: (a + b) / 2)
    assert slept == [2.0], slept
    print("jittered_delay: ok")


if __name__ == "__main__":
    test_sliding_window_limiter()
    test_with_retries_succeeds_after_failures()
    test_with_retries_gives_up()
    test_jittered_delay_noop_when_zero()
    print("ALL THROTTLE TESTS PASSED")
