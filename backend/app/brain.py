"""Layer D/E analytics that need no LLM — LinkedIn edition.

Author baselines + outlier scoring (reactions ÷ author median) over the Raw Lake.
LLM-powered mining (patterns/pain-points/style) lives in insights.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

from sqlmodel import Session, select

from .models import LinkedInPost, PainPoint, PostComment


@dataclass
class ChannelBaseline:
    channel_id: str        # author_id
    channel_name: str | None
    video_count: int       # post count
    median_views: float    # median reactions


@dataclass
class Outlier:
    video_id: str          # post_id
    title: str             # post text excerpt
    channel_id: str        # author_id
    views: int             # reactions
    channel_median: float  # author median reactions
    multiplier: float


def channel_baselines(session: Session) -> list[ChannelBaseline]:
    posts = session.exec(select(LinkedInPost)).all()
    by_author: dict[str, list[LinkedInPost]] = {}
    for p in posts:
        by_author.setdefault(p.author_id, []).append(p)

    out: list[ChannelBaseline] = []
    for author_id, ps in by_author.items():
        reactions = [p.reactions for p in ps if p.reactions > 0]
        out.append(
            ChannelBaseline(
                channel_id=author_id,
                channel_name=next((p.author_name for p in ps if p.author_name), None),
                video_count=len(ps),
                median_views=float(median(reactions)) if reactions else 0.0,
            )
        )
    return sorted(out, key=lambda b: b.video_count, reverse=True)


def outliers(session: Session, *, min_multiplier: float = 1.0, limit: int = 50) -> list[Outlier]:
    baselines = {b.channel_id: b.median_views for b in channel_baselines(session)}
    posts = session.exec(select(LinkedInPost)).all()

    rows: list[Outlier] = []
    for p in posts:
        med = baselines.get(p.author_id, 0.0)
        if med <= 0:
            continue
        mult = round(p.reactions / med, 2)
        if mult >= min_multiplier:
            rows.append(
                Outlier(
                    video_id=p.id,
                    title=p.text[:120].replace("\n", " "),
                    channel_id=p.author_id,
                    views=p.reactions,
                    channel_median=med,
                    multiplier=mult,
                )
            )
    return sorted(rows, key=lambda o: o.multiplier, reverse=True)[:limit]


@dataclass
class Trending:
    video_id: str          # post_id
    title: str             # post text excerpt
    channel_id: str        # author_id
    views: int             # reactions
    velocity: float        # reactions per day since publish
    multiplier: float
    published_at: str


def trending(session: Session, *, days_window: int = 90, limit: int = 12) -> list[Trending]:
    """What's performing now: recent posts ranked by velocity (reactions ÷ days since publish)."""
    now = datetime.utcnow()
    medians = {b.channel_id: b.median_views for b in channel_baselines(session)}
    rows: list[Trending] = []
    for p in session.exec(select(LinkedInPost)).all():
        if p.published_at is None or p.reactions <= 0:
            continue
        age_days = max(1, (now - p.published_at).days)
        if age_days > days_window:
            continue
        med = medians.get(p.author_id, 0.0)
        rows.append(
            Trending(
                video_id=p.id,
                title=p.text[:120].replace("\n", " "),
                channel_id=p.author_id,
                views=p.reactions,
                velocity=round(p.reactions / age_days, 1),
                multiplier=round(p.reactions / med, 2) if med > 0 else 0.0,
                published_at=p.published_at.date().isoformat(),
            )
        )
    return sorted(rows, key=lambda r: r.velocity, reverse=True)[:limit]


def content_gaps(
    session: Session, *, niche: str | None = None, coverage_threshold: float = 0.12, limit: int = 20
) -> list[dict]:
    """Audience pain-points the existing posts barely cover = best next posts.

    Coverage uses TF-IDF similarity against post text corpus.
    """
    from sqlmodel import select as _select

    q = _select(PainPoint)
    if niche:
        q = q.where(PainPoint.niche == niche)
    pains = list(session.exec(q.order_by(PainPoint.frequency.desc())).all())
    if not pains:
        return []

    corpus = [p.text for p in session.exec(select(LinkedInPost)).all() if p.text]

    def _bare(cov: float) -> list[dict]:
        return [
            {"question": p.question, "frequency": p.frequency, "coverage": cov, "covered": False}
            for p in pains[:limit]
        ]

    if not corpus:
        return _bare(0.0)
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return _bare(0.0)

    questions = [p.question for p in pains]
    vec = TfidfVectorizer(stop_words="english", max_features=4096)
    matrix = vec.fit_transform(corpus + questions)
    n = len(corpus)
    sims = cosine_similarity(matrix[n:], matrix[:n])

    gaps = []
    for i, p in enumerate(pains):
        cov = round(float(sims[i].max()), 3) if sims.shape[1] else 0.0
        gaps.append(
            {"question": p.question, "frequency": p.frequency, "coverage": cov,
             "covered": cov >= coverage_threshold}
        )
    gaps.sort(key=lambda g: (g["covered"], -g["frequency"], g["coverage"]))
    return gaps[:limit]
