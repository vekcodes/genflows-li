"""Novelty check for generated ideas — keeps output from being a near-copy of one existing video.

Cheap + dependency-free: compares a candidate title against the titles already in the Brain
(scraped videos) and already in the content queue, using the max of a sequence-ratio and a
token-set Jaccard. Used *alongside* the virality model: an idea must be both novel AND score
well to survive. The virality model stays the numeric gate; this only removes rip-offs.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlmodel import Session, select

from ..models import ContentItem, Video

_WORD = re.compile(r"[a-z0-9']+")
# Common YouTube-title filler that shouldn't count toward "same title".
_STOP = frozenset(
    "the a an to of for and or in on with how why what your you my is are this that these "
    "best top vs from at it i".split()
)


def _norm(title: str) -> str:
    return " ".join(_WORD.findall((title or "").lower()))


def _tokens(title: str) -> set[str]:
    return {w for w in _WORD.findall((title or "").lower()) if w not in _STOP}


def similarity(a: str, b: str) -> float:
    """0..1 — how alike two titles are (1 = effectively the same)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0
    return max(ratio, jaccard)


def max_similarity(title: str, existing: list[str]) -> float:
    """Highest similarity between `title` and any existing title (0 if none)."""
    return max((similarity(title, e) for e in existing), default=0.0)


def existing_titles(session: Session, channel_id: str | None = None) -> list[str]:
    """Titles already known to the Brain: scraped videos + queued/proposed content items."""
    vq = select(Video.title)
    if channel_id:
        vq = vq.where(Video.channel_id == channel_id)
    titles = [t for t in session.exec(vq).all() if t]
    titles += [t for t in session.exec(select(ContentItem.title)).all() if t]
    return titles
