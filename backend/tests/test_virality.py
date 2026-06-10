"""Validate the virality backtester on synthetic data with a KNOWN signal.

We plant a real relationship — listicle/numbered titles go viral, plain titles
don't — then assert the backtest *recovers* it (AUC well above chance) and that
scoring ranks a numbered-listicle title above a plain one. This is the meta-test
that the "backtested for virality" claim actually holds.

Run:  .venv/Scripts/python.exe -m pytest tests/ -q     (or run this file directly)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("BRAIN_DATABASE_URL", "sqlite:///./_virality_test.db")
os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")


def _make_session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed(session, total: int = 120):
    """One channel. ~1 in 4 videos is a numbered-listicle that goes viral (10x);
    the rest are plain baseline videos. Non-viral dominates, so the channel median
    stays at baseline and viral videos clear the 3x threshold (like real outliers).
    Both classes are spread across the timeline so the time-split sees both."""
    from app.models import Video

    start = datetime(2025, 1, 1)
    base_views = 50_000  # plain majority -> channel median lands here
    for i in range(total):
        day = start + timedelta(days=i)
        if i % 4 == 0:  # viral
            session.add(Video(
                id=f"v{i}", channel_id="ch", channel_name="Test",
                title=f"{i % 9 + 3} Mistakes Killing Your Edits",
                views=base_views * 10, duration_sec=600, published_at=day,
            ))
        else:  # non-viral
            session.add(Video(
                id=f"v{i}", channel_id="ch", channel_name="Test",
                title="A calm chat about my week",
                views=base_views, duration_sec=600, published_at=day,
            ))
    session.commit()


def test_backtest_recovers_planted_signal():
    from app import virality

    session = _make_session()
    _seed(session)

    report = virality.backtest(session, threshold=3.0)
    assert report["status"] == "ok", report
    assert report["n"] == 120 and report["n_viral"] == 30, report
    # The signal is strong and clean → the held-out backtest should be near-perfect.
    assert report["roc_auc"] is not None and report["roc_auc"] >= 0.9, report
    assert report["precision_at_k"] >= 0.9, report
    # "is_listicle" / "has_number" should be among the strongest drivers.
    drivers = {f["feature"] for f in report["top_features"]}
    assert drivers & {"is_listicle", "has_number"}, report
    print("backtest:", {k: report[k] for k in ("n", "roc_auc", "precision_at_k", "lift_at_k", "spearman_corr")})


def test_score_ranks_listicle_above_plain():
    from app import virality

    session = _make_session()
    _seed(session)

    viral_like = virality.score(session, title="7 Editing Mistakes Killing Your Retention", duration_sec=600)
    plain_like = virality.score(session, title="just hanging out and chatting today", duration_sec=600)
    assert viral_like["status"] == "ok" and plain_like["status"] == "ok"
    assert viral_like["virality_score"] > plain_like["virality_score"], (viral_like, plain_like)
    assert viral_like["format"] == "listicle"
    assert viral_like["nearest_analogs"], "expected proven analogs"
    print("score(listicle):", viral_like["virality_score"], "| score(plain):", plain_like["virality_score"])


def test_insufficient_data_is_graceful():
    from app import virality

    session = _make_session()  # empty
    report = virality.backtest(session)
    assert report["status"] == "insufficient_data", report


if __name__ == "__main__":
    test_backtest_recovers_planted_signal()
    test_score_ranks_listicle_above_plain()
    test_insufficient_data_is_graceful()
    print("ALL VIRALITY TESTS PASSED")
