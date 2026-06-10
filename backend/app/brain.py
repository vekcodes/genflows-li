"""Layer D/E analytics that need no LLM: channel baselines + outlier scoring.

Outlier scoring (views ÷ channel median) is the single highest-value signal and
is pure computation over the Raw Lake, so it works the moment videos are ingested.
LLM-powered mining (patterns/pain-points/style) lives in the API layer behind the
LLM provider and is stubbed until a provider is configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

from sqlmodel import Session, select

from .models import Chunk, PainPoint, Video


@dataclass
class ChannelBaseline:
    channel_id: str
    channel_name: str | None
    video_count: int
    median_views: float


@dataclass
class Outlier:
    video_id: str
    title: str
    channel_id: str
    views: int
    channel_median: float
    multiplier: float


def channel_baselines(session: Session) -> list[ChannelBaseline]:
    videos = session.exec(select(Video)).all()
    by_channel: dict[str, list[Video]] = {}
    for v in videos:
        by_channel.setdefault(v.channel_id, []).append(v)

    out: list[ChannelBaseline] = []
    for channel_id, vids in by_channel.items():
        views = [v.views for v in vids if v.views > 0]
        out.append(
            ChannelBaseline(
                channel_id=channel_id,
                channel_name=next((v.channel_name for v in vids if v.channel_name), None),
                video_count=len(vids),
                median_views=float(median(views)) if views else 0.0,
            )
        )
    return sorted(out, key=lambda b: b.video_count, reverse=True)


def outliers(session: Session, *, min_multiplier: float = 1.0, limit: int = 50) -> list[Outlier]:
    baselines = {b.channel_id: b.median_views for b in channel_baselines(session)}
    videos = session.exec(select(Video)).all()

    rows: list[Outlier] = []
    for v in videos:
        med = baselines.get(v.channel_id, 0.0)
        if med <= 0:
            continue
        mult = round(v.views / med, 2)
        if mult >= min_multiplier:
            rows.append(
                Outlier(
                    video_id=v.id,
                    title=v.title,
                    channel_id=v.channel_id,
                    views=v.views,
                    channel_median=med,
                    multiplier=mult,
                )
            )
    return sorted(rows, key=lambda o: o.multiplier, reverse=True)[:limit]


@dataclass
class Trending:
    video_id: str
    title: str
    channel_id: str
    views: int
    velocity: float  # views per day since publish
    multiplier: float
    published_at: str


def trending(session: Session, *, days_window: int = 180, limit: int = 12) -> list[Trending]:
    """What's hot *now*: recent videos ranked by velocity (views ÷ days since publish).

    Captures momentum rather than all-time totals, so a 2-month-old rocket outranks an
    old evergreen. Used to bias generation toward currently-trending themes.
    """
    now = datetime.utcnow()
    medians = {b.channel_id: b.median_views for b in channel_baselines(session)}
    rows: list[Trending] = []
    for v in session.exec(select(Video)).all():
        if v.published_at is None or v.views <= 0:
            continue
        age_days = max(1, (now - v.published_at).days)
        if age_days > days_window:
            continue
        med = medians.get(v.channel_id, 0.0)
        rows.append(
            Trending(
                video_id=v.id,
                title=v.title,
                channel_id=v.channel_id,
                views=v.views,
                velocity=round(v.views / age_days, 1),
                multiplier=round(v.views / med, 2) if med > 0 else 0.0,
                published_at=v.published_at.date().isoformat(),
            )
        )
    return sorted(rows, key=lambda r: r.velocity, reverse=True)[:limit]


def content_gaps(
    session: Session, *, niche: str | None = None, coverage_threshold: float = 0.12, limit: int = 20
) -> list[dict]:
    """Audience pain-points the existing content barely covers = your best next videos.

    Coverage = max TF-IDF similarity of the pain-point question against the corpus
    (transcript chunks, or video titles as a fallback). Low coverage + high frequency = gap.
    """
    q = select(PainPoint)
    if niche:
        q = q.where(PainPoint.niche == niche)
    pains = list(session.exec(q.order_by(PainPoint.frequency.desc())).all())
    if not pains:
        return []

    corpus = [c for c in session.exec(select(Chunk.text)).all() if c]
    if not corpus:
        corpus = [v.title for v in session.exec(select(Video)).all() if v.title]

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
    except ImportError:  # pragma: no cover
        return _bare(0.0)

    questions = [p.question for p in pains]
    vec = TfidfVectorizer(stop_words="english", max_features=4096)
    matrix = vec.fit_transform(corpus + questions)
    n = len(corpus)
    sims = cosine_similarity(matrix[n:], matrix[:n])  # (questions x corpus)

    gaps = []
    for i, p in enumerate(pains):
        cov = round(float(sims[i].max()), 3) if sims.shape[1] else 0.0
        gaps.append(
            {"question": p.question, "frequency": p.frequency, "coverage": cov,
             "covered": cov >= coverage_threshold}
        )
    gaps.sort(key=lambda g: (g["covered"], -g["frequency"], g["coverage"]))
    return gaps[:limit]
